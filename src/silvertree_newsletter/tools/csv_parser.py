"""CSV parsing utilities for portfolio companies."""

from __future__ import annotations

import csv
from pathlib import Path

from silvertree_newsletter.models.schemas import Company


def load_portfolio_companies(csv_path: str | Path) -> list[Company]:
    """Load portfolio companies from the tracking scope CSV."""
    path = Path(csv_path)
    companies: list[Company] = []

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = (row.get("PortfolioCompany") or "").strip()
            if not name:
                continue
            sector = (row.get("Sector") or "").strip() or None
            companies.append(
                Company(
                    name=name,
                    sector=sector,
                    is_portfolio_company=True,
                )
            )

    return companies
