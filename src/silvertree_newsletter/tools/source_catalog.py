"""Load source catalog for RSS and domain-based searches."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SourceCatalog:
    rss_feeds: dict[str, str]
    domain_sources: list[str]
    trusted_domains: list[str]
    notes: list[str]


def load_source_catalog(path: str | Path) -> SourceCatalog:
    catalog_path = Path(path)
    if not catalog_path.exists():
        return SourceCatalog(rss_feeds={}, domain_sources=[], trusted_domains=[], notes=[])

    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    rss_feeds = data.get("rss_feeds", {}) or {}
    domain_sources = data.get("domain_sources", []) or []
    trusted_domains = data.get("trusted_domains", []) or []
    notes = data.get("notes", []) or []

    return SourceCatalog(
        rss_feeds=rss_feeds,
        domain_sources=domain_sources,
        trusted_domains=trusted_domains,
        notes=notes,
    )
