"""SMTP delivery for watch-match digest emails.

Kept deliberately small: stdlib smtplib + email.message.EmailMessage, no
external mailer dependency. The notifier (``notifier/checker.py``) batches
matches per (user, watch) and asks this module to send a single digest
per batch.

If SMTP isn't configured we don't raise -- callers check
``is_smtp_configured()`` first and skip the send. This keeps Pharos
fully usable without an SMTP relay; users just won't get emails.
"""
from __future__ import annotations

import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Sequence

from ..config import get_settings

log = logging.getLogger(__name__)


# Loose-but-pragmatic email validation. Real validation is "did the relay
# accept it?" -- this just rejects obvious garbage at the API edge so we
# don't queue undeliverable rows.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(addr: str | None) -> bool:
    return bool(addr) and bool(_EMAIL_RE.match(addr.strip()))


def is_smtp_configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host)


@dataclass(slots=True)
class DigestArticle:
    """One row in the digest body."""
    article_id: int
    title: str
    feed_title: str | None
    published_at: str | None
    overview: str | None
    severity_hint: str | None


def _public_article_url(article_id: int) -> str:
    """Build a clickable link to the article in the SPA.

    The frontend opens articles inside a slide-in drawer, addressed by
    the ``article`` query string on the stream route.
    """
    base = (get_settings().pharos_public_url or "").rstrip("/")
    path = f"/stream?article={article_id}"
    return f"{base}{path}" if base else path


def render_digest(
    *,
    watch_name: str,
    articles: Sequence[DigestArticle],
) -> tuple[str, str, str]:
    """Return (subject, plain_text_body, html_body) for the digest."""
    n = len(articles)
    suffix = "" if n == 1 else "es"
    subject = f"[Pharos] {watch_name}: {n} new match{suffix}"

    # ----- plain text -----
    lines: list[str] = [
        f'New articles matching "{watch_name}":',
        "",
    ]
    for a in articles:
        meta_bits = [b for b in (a.feed_title, a.published_at) if b]
        meta = " · ".join(meta_bits)
        lines.append(f"• {a.title}")
        if meta:
            lines.append(f"  {meta}")
        if a.overview:
            # Tighten to roughly two short paragraphs so the email isn't
            # 80 KB when 50 articles match the same watch.
            ov = a.overview.strip().replace("\n", " ")
            if len(ov) > 320:
                ov = ov[:320].rstrip() + "…"
            lines.append(f"  {ov}")
        lines.append(f"  {_public_article_url(a.article_id)}")
        lines.append("")
    lines.append("--")
    lines.append("Pharos -- Open Source AI-enabled news aggregator")
    text = "\n".join(lines)

    # ----- html -----
    html_rows: list[str] = []
    for a in articles:
        meta_bits = [b for b in (a.feed_title, a.published_at) if b]
        meta = " &middot; ".join(_html_escape(b) for b in meta_bits)
        sev = (
            f' <span style="background:#fbe9e7;color:#b71c1c;padding:1px 6px;'
            f'border-radius:6px;font-size:11px;text-transform:uppercase;'
            f'letter-spacing:.05em">{_html_escape(a.severity_hint)}</span>'
            if a.severity_hint else ""
        )
        ov = a.overview or ""
        if len(ov) > 320:
            ov = ov[:320].rstrip() + "…"
        html_rows.append(
            "<tr><td style=\"padding:14px 0;border-top:1px solid #eee\">"
            f"<a href=\"{_html_escape(_public_article_url(a.article_id))}\" "
            "style=\"font-weight:600;font-size:15px;color:#1a2233;"
            "text-decoration:none\">"
            f"{_html_escape(a.title)}</a>{sev}"
            f"<div style=\"color:#777;font-size:12px;margin-top:2px\">{meta}</div>"
            f"<div style=\"color:#444;font-size:13px;margin-top:6px\">"
            f"{_html_escape(ov)}</div>"
            "</td></tr>"
        )
    html = (
        "<!doctype html><html><body style=\"margin:0;padding:0;"
        "background:#f7f7f9;font-family:-apple-system,BlinkMacSystemFont,"
        "'Segoe UI',Roboto,Helvetica,Arial,sans-serif\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\""
        " style=\"max-width:640px;margin:0 auto;background:#fff;padding:24px\">"
        f"<tr><td style=\"padding-bottom:8px\"><div style=\"font-size:12px;"
        f"color:#888;text-transform:uppercase;letter-spacing:.08em;font-weight:600\">"
        f"Pharos watch update</div><h1 style=\"margin:6px 0 0;font-size:20px;"
        f"color:#1a2233\">{_html_escape(watch_name)}</h1>"
        f"<div style=\"color:#666;font-size:13px;margin-top:4px\">"
        f"{n} new match{suffix} since the last digest.</div></td></tr>"
        + "".join(html_rows)
        + "<tr><td style=\"padding-top:18px;color:#999;font-size:11px\">"
        "You are receiving this because you enabled email digests for this watch. "
        "Manage your watches in Pharos &rarr; Watches."
        "</td></tr></table></body></html>"
    )
    return subject, text, html


def _html_escape(s: str | None) -> str:
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def send_email(
    *,
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
) -> None:
    """Send a single MIME email via the configured SMTP relay.

    Raises ``RuntimeError`` if SMTP isn't configured (callers should gate
    on ``is_smtp_configured()`` first to avoid this).
    """
    s = get_settings()
    if not s.smtp_host:
        raise RuntimeError("SMTP is not configured (set SMTP_HOST)")

    sender = (s.smtp_from or s.smtp_user or "").strip()
    if not sender:
        raise RuntimeError("SMTP_FROM (or SMTP_USER) must be set")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Pharos", sender))
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="pharos.local")
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    if s.smtp_use_ssl:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ctx, timeout=30) as smtp:
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            if not s.smtp_skip_starttls:
                try:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                except smtplib.SMTPException:
                    # Some local relays don't advertise STARTTLS. Carry on
                    # cleartext rather than refuse to deliver -- the user
                    # opted in via SMTP_SKIP_STARTTLS=false but the relay
                    # itself doesn't support it.
                    log.warning("STARTTLS failed; continuing in cleartext")
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    log.info("sent digest email to %s (%s)", to, subject)
