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
    ReportRequest,
    ReportResult,
    collect_articles,
    generate_report,
    estimate_cost,
)

__all__ = [
    "ReportRequest",
    "ReportResult",
    "collect_articles",
    "generate_report",
    "estimate_cost",
]
