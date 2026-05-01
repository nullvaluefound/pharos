"""Report generation: turn a filtered set of enriched articles into a
finished threat-intel report (BLUF / custom sections, executive / technical
/ both audiences, configurable length).

Public surface:
  - ``generate_report``       -- async helper that talks to OpenAI
  - ``collect_articles``      -- run a SearchQuery and return the article
                                 rows that should feed a report
  - ``ReportRequest`` / ``ReportResult`` dataclasses
"""
from .generator import (
    MAX_ARTICLES,
    ReportRequest,
    ReportResult,
    collect_articles,
    count_articles_in_scope,
    estimate_cost,
    generate_report,
)

__all__ = [
    "MAX_ARTICLES",
    "ReportRequest",
    "ReportResult",
    "collect_articles",
    "count_articles_in_scope",
    "estimate_cost",
    "generate_report",
]
