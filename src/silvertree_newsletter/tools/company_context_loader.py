"""Load portfolio company context from JSON."""

from __future__ import annotations

import json
from pathlib import Path

from silvertree_newsletter.models.schemas import CompanyProfile, CompetitorCluster


def load_company_context(
    json_path: str | Path,
) -> tuple[list[CompanyProfile], list[CompetitorCluster]]:
    """Load portfolio companies and competitor clusters from JSON."""
    path = Path(json_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    companies = [CompanyProfile(**item) for item in data.get("companies", [])]
    clusters = [CompetitorCluster(**item) for item in data.get("competitor_clusters", [])]

    return companies, clusters
