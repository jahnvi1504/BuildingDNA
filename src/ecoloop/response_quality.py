from __future__ import annotations

import html
import re


GENERIC_OUTPUT_PHRASES = (
    "this is a json",
    "this is a json data",
    "here's a breakdown",
    "here is a breakdown",
    "the data contains",
    "the data provided",
    "without more context",
    "unknown field",
    "likely using energyplus",
    "likely using the energyplus",
    "json data dump",
    "overall, this data",
    "this data provides",
    "collection of simulation results",
    "general insights based on this data",
)

NON_ACTIONABLE_LABEL = "LLM response was non-actionable; deterministic fallback used."

_SCHEMA_LINE = re.compile(
    r"(?im)^\s*\d+[\.\)]\s*(?:\*\*)?"
    r"(?:simulation|day|hour|minute|field|zone|pmv|energy|carbon|heating|cooling|"
    r"comfort|macro|reflex)"
)


def strip_markdown_fences(value: str) -> str:
    text = value.strip()
    if not text.startswith("```"):
        return text
    text = re.sub(r"^```(?:json)?\s*", "", text, count=1, flags=re.IGNORECASE)
    return re.sub(r"\s*```$", "", text, count=1).strip()


def is_low_quality_output(value: str) -> bool:
    lowered = value.casefold()
    if any(phrase in lowered for phrase in GENERIC_OUTPUT_PHRASES):
        return True
    return len(_SCHEMA_LINE.findall(value)) >= 2


def truncate_text(value: object, limit: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def escaped_truncated(value: object, limit: int = 500) -> str:
    return html.escape(truncate_text(value, limit))
