"""Render a saved report into the (subject, plaintext, HTML) tuple the
mailer expects.

Reports are stored as Markdown (``reports.body_md``). For email we keep
the plaintext part as the original markdown source -- modern mail clients
render it readably -- and produce a styled HTML part for the rest.

We deliberately keep the HTML inline-styled rather than relying on
external CSS, because a depressing number of email clients (Gmail
mobile in particular) strip <style> blocks.
"""
from __future__ import annotations

from typing import Iterable

import markdown as md_lib

from ..config import get_settings


# A small subset of markdown-extra features. We don't need pygments or
# image embedding for a threat-intel briefing.
_MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "nl2br"]


def _public_report_url(report_id: int) -> str:
    base = (get_settings().pharos_public_url or "").rstrip("/")
    path = f"/reports?open={report_id}"
    return f"{base}{path}" if base else path


def _meta_line(*, audience: str, length_target: str, structure_kind: str,
               article_count: int, cost_usd: float | None) -> str:
    bits: list[str] = [
        f"{article_count} article{'' if article_count == 1 else 's'}",
        _audience_label(audience),
        _length_label(length_target),
        structure_kind,
    ]
    if cost_usd is not None:
        bits.append(f"${cost_usd:.3f}")
    return " · ".join(bits)


def _audience_label(value: str) -> str:
    return {"both": "Exec + Tech", "executive": "Executive", "technical": "Technical"}.get(value, value)


def _length_label(value: str) -> str:
    return {"short": "1-2 pp", "medium": "2-3 pp", "long": "3-4 pp"}.get(value, value)


def render_report_email(
    *,
    report_name: str,
    report_id: int,
    body_md: str,
    audience: str,
    length_target: str,
    structure_kind: str,
    article_count: int,
    cost_usd: float | None,
    schedule_name: str | None = None,
) -> tuple[str, str, str]:
    """Build (subject, text_body, html_body)."""
    if schedule_name:
        subject = f"[Pharos] {schedule_name}: {report_name}"
    else:
        subject = f"[Pharos] Report: {report_name}"

    meta = _meta_line(
        audience=audience,
        length_target=length_target,
        structure_kind=structure_kind,
        article_count=article_count,
        cost_usd=cost_usd,
    )
    open_url = _public_report_url(report_id)

    # ----- plaintext part -----
    text_lines: list[str] = [
        report_name,
        "=" * len(report_name),
        meta,
        "",
        body_md.strip(),
        "",
        "--",
        f"Open in Pharos: {open_url}" if open_url.startswith("http") else "Open in Pharos.",
    ]
    text = "\n".join(text_lines).strip() + "\n"

    # ----- HTML part -----
    rendered = md_lib.markdown(body_md or "", extensions=_MD_EXTENSIONS)
    html = _wrap_html(
        title=report_name,
        meta=meta,
        body_html=rendered,
        open_url=open_url,
    )
    return subject, text, html


def _wrap_html(*, title: str, meta: str, body_html: str, open_url: str) -> str:
    return (
        '<!doctype html><html><body style="margin:0;padding:0;'
        'background:#f7f7f9;font-family:-apple-system,BlinkMacSystemFont,'
        "'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1a2233\">"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        ' style="max-width:720px;margin:0 auto;background:#ffffff;'
        'padding:32px 28px;line-height:1.55">'
        '<tr><td>'
        '<div style="font-size:11px;color:#888;text-transform:uppercase;'
        'letter-spacing:.1em;font-weight:600;margin-bottom:6px">'
        'Pharos report</div>'
        f'<h1 style="margin:0 0 6px;font-size:22px;font-weight:700;color:#1a2233">'
        f'{_html_escape(title)}</h1>'
        f'<div style="color:#666;font-size:13px;margin-bottom:24px">{_html_escape(meta)}</div>'
        '<div style="font-size:14px;color:#222">'
        + _style_body(body_html)
        + '</div>'
        '<div style="margin-top:32px;padding-top:18px;border-top:1px solid #eee;'
        'color:#888;font-size:12px">'
        + (
            f'<a href="{_html_escape(open_url)}" '
            'style="color:#0d63d1;text-decoration:none;font-weight:600">'
            'Open this report in Pharos &rarr;</a>'
            if open_url.startswith("http")
            else "Open this report in Pharos."
        )
        + '<br><span style="color:#aaa">You are receiving this because the '
        "report was shared with you, or because a Pharos schedule produced it.</span>"
        '</td></tr></table></body></html>'
    )


def _style_body(html: str) -> str:
    """Bolt inline styles onto the rendered markdown so the email renders
    correctly in clients that strip <style> blocks (most of them).

    We avoid pulling in a full HTML parser -- a small set of literal tag
    substitutions is enough because python-markdown's output is
    well-behaved and stable.
    """
    replacements: Iterable[tuple[str, str]] = (
        ("<h1>",
         '<h1 style="font-size:20px;font-weight:700;color:#1a2233;'
         'margin:24px 0 8px;border-bottom:1px solid #eee;padding-bottom:6px">'),
        ("<h2>",
         '<h2 style="font-size:17px;font-weight:700;color:#1a2233;'
         'margin:22px 0 6px;border-bottom:1px solid #eee;padding-bottom:4px">'),
        ("<h3>",
         '<h3 style="font-size:15px;font-weight:600;color:#1a2233;'
         'margin:18px 0 4px">'),
        ("<h4>",
         '<h4 style="font-size:14px;font-weight:600;color:#1a2233;'
         'margin:16px 0 4px">'),
        ("<p>",
         '<p style="margin:0 0 12px;color:#222">'),
        ("<ul>",
         '<ul style="margin:0 0 12px;padding-left:22px">'),
        ("<ol>",
         '<ol style="margin:0 0 12px;padding-left:22px">'),
        ("<li>",
         '<li style="margin:2px 0">'),
        ("<blockquote>",
         '<blockquote style="margin:0 0 12px;padding:6px 14px;'
         'border-left:3px solid #d0d7e2;color:#555;background:#f5f7fa">'),
        ("<code>",
         '<code style="background:#f1f3f7;padding:1px 4px;border-radius:3px;'
         'font-family:Menlo,Consolas,monospace;font-size:12px;color:#1a2233">'),
        ("<pre>",
         '<pre style="background:#f1f3f7;padding:10px 12px;border-radius:6px;'
         'overflow:auto;font-family:Menlo,Consolas,monospace;font-size:12px;'
         'line-height:1.45;color:#1a2233;margin:0 0 12px">'),
        ("<a ",
         '<a style="color:#0d63d1;text-decoration:underline" '),
        ("<table>",
         '<table style="border-collapse:collapse;margin:0 0 14px;width:100%">'),
        ("<th>",
         '<th style="text-align:left;padding:6px 8px;border-bottom:2px solid #ccc;'
         'font-size:13px;color:#1a2233">'),
        ("<td>",
         '<td style="padding:6px 8px;border-bottom:1px solid #eee;font-size:13px">'),
        ("<hr>",
         '<hr style="border:0;border-top:1px solid #eee;margin:18px 0">'),
        ("<hr/>",
         '<hr style="border:0;border-top:1px solid #eee;margin:18px 0">'),
    )
    out = html
    for needle, repl in replacements:
        out = out.replace(needle, repl)
    return out


def _html_escape(s: str | None) -> str:
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
