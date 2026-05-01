"""Thin wrapper around the OpenAI SDK that returns a validated EnrichedArticle.

We use ``client.beta.chat.completions.parse`` with the Pydantic
``EnrichedArticle`` model as the response_format. This activates OpenAI's
*strict* structured-output mode, which:

  * forbids the model from emitting any field that isn't in the schema, and
  * forbids it from omitting any required field.

The combination guarantees the JSON we get back can always be parsed and
mapped to ``EnrichedArticle`` without us hand-rolling JSON Schema cleanup.

Pydantic validates the result a second time on our side (defense in depth +
catches semantic violations like an unknown MITRE Technique ID, since
strict mode only enforces structure).

Two extra robustness layers:

  1. We retry once with a slightly more forceful "respond with valid JSON"
     prompt if validation fails.
  2. ``OPENAI_TOOLS=web_search_preview`` (or any other supported tool name)
     attaches OpenAI's hosted tools so the model can verify novel actor /
     malware attributions against the live web. Off by default.
"""
from __future__ import annotations

import asyncio
import logging
import os

from openai import AsyncOpenAI

from ..config import get_settings
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schema import EnrichedArticle

log = logging.getLogger(__name__)


class LanternLLMError(RuntimeError):
    """Raised when the LLM call or its output cannot be salvaged."""


def _client() -> AsyncOpenAI:
    s = get_settings()
    if not s.openai_api_key:
        raise LanternLLMError("OPENAI_API_KEY is not set")

    # The OpenAI SDK reads OPENAI_BASE_URL directly from os.environ. Our
    # .env ships with an empty `OPENAI_BASE_URL=` placeholder, which the SDK
    # would treat as a literal empty base URL. Strip empty values to fall
    # back to the SDK default of https://api.openai.com/v1.
    if os.environ.get("OPENAI_BASE_URL", "").strip() == "":
        os.environ.pop("OPENAI_BASE_URL", None)

    base = (s.openai_base_url or "").strip() or None
    return AsyncOpenAI(api_key=s.openai_api_key, base_url=base)


def _is_reasoning_model(model: str) -> bool:
    """o-series reasoning models reject custom temperature/top_p."""
    m = model.lower()
    return m.startswith(("o1", "o3", "o4")) or "reasoning" in m


def _tools() -> list[dict] | None:
    """Parse PHAROS_OPENAI_TOOLS / OPENAI_TOOLS env into a tool spec list.

    Currently only OpenAI's hosted ``web_search_preview`` is supported.
    """
    s = get_settings()
    raw = (s.openai_tools or "").strip()
    if not raw:
        return None
    out: list[dict] = []
    for name in (n.strip() for n in raw.split(",")):
        if not name:
            continue
        if name in {"web_search", "web_search_preview"}:
            out.append({"type": "web_search_preview"})
        else:
            log.warning("ignoring unknown openai tool %r in OPENAI_TOOLS", name)
    return out or None


_RETRY_SUFFIX = (
    "\n\nIMPORTANT: Respond with the EnrichedArticle JSON object only. "
    "Every required field must be present. If a list has no items, return "
    "an empty list. If a value is unknown, use null. Do not add commentary."
)


async def enrich(*, title: str | None, url: str, body: str) -> EnrichedArticle:
    """Send an article to the LLM and return the validated EnrichedArticle.

    Retries once on validation failure with a forceful "respond with valid
    JSON" reminder appended to the user prompt.
    """
    s = get_settings()
    client = _client()

    user_prompt = build_user_prompt(title=title, url=url, body=body)
    tools = _tools()

    async def _call(extra_user_suffix: str = "") -> EnrichedArticle:
        kwargs: dict = dict(
            model=s.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt + extra_user_suffix},
            ],
            response_format=EnrichedArticle,
            # gpt-4o caps completion at 16384 tokens. Strict structured
            # output mode rejects the entire call if the model would
            # overflow, so we sit at ~half the limit. 8000 tokens is
            # roughly enough for ~60 entities across all categories
            # which covers even the densest "this week in security"
            # roundup posts. A typical news article uses well under
            # 1500 tokens, so this is just headroom insurance.
            max_tokens=8000,
        )
        if not _is_reasoning_model(s.openai_model):
            kwargs["temperature"] = 0.0
        if tools:
            kwargs["tools"] = tools

        try:
            response = await client.beta.chat.completions.parse(**kwargs)
        except Exception as exc:
            raise LanternLLMError(f"OpenAI request failed: {exc}") from exc

        if not response.choices:
            raise LanternLLMError("OpenAI returned no choices")

        choice = response.choices[0]
        if choice.message.refusal:
            raise LanternLLMError(
                f"OpenAI refused enrichment: {choice.message.refusal}"
            )

        parsed = choice.message.parsed
        if parsed is None:
            # Fallback: parse() failed silently (rare, usually means the
            # SDK couldn't reconcile output with the schema). Try one more
            # time with the manual model_validate path on the raw content.
            raw = choice.message.content or ""
            if not raw:
                raise LanternLLMError("OpenAI returned no parsed output and no content")
            try:
                import json as _json
                return EnrichedArticle.model_validate(_json.loads(raw))
            except Exception as exc:
                raise LanternLLMError(
                    f"EnrichedArticle validation failed: {exc}"
                ) from exc

        # parse() already returned an EnrichedArticle, but run our own
        # field validators (catalog membership checks, CVE normalisation)
        # by re-validating the dump.
        try:
            return EnrichedArticle.model_validate(parsed.model_dump())
        except Exception as exc:
            raise LanternLLMError(
                f"EnrichedArticle re-validation failed: {exc}"
            ) from exc

    try:
        return await _call()
    except LanternLLMError as exc:
        # One retry with a forceful suffix; helps when the model returns
        # mostly-valid JSON but the catalog-membership re-validator dropped
        # everything and the upstream request raised on something else.
        msg = str(exc).lower()
        if "validation" in msg or "invalid json" in msg:
            log.info("retrying enrichment after validation failure: %s", exc)
            await asyncio.sleep(0.5)
            return await _call(_RETRY_SUFFIX)
        raise
