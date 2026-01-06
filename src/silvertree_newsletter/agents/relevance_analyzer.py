"""LLM-powered relevance analyzer for news items.

Determines:
1. Relevance to SilverTree portfolio companies
2. Relevance to competitors
3. Deal type classification (M&A, fundraising, partnership, etc.)
4. Why it matters (relevance explanation)
5. Carve-out potential for M&A deals
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import google.generativeai as genai

from silvertree_newsletter.models.schemas import (
    NewsItem,
    RelevanceLevel,
    NewsCategory,
)

logger = logging.getLogger(__name__)


class DealType(str, Enum):
    """Type of deal/transaction."""
    MA_ACQUISITION = "ma_acquisition"
    MA_MERGER = "ma_merger"
    DIVESTITURE = "divestiture"
    FUNDRAISING = "fundraising"
    IPO = "ipo"
    PARTNERSHIP = "partnership"
    PRODUCT_LAUNCH = "product_launch"
    PERSONNEL_CHANGE = "personnel_change"
    STRATEGIC_UPDATE = "strategic_update"
    NOT_A_DEAL = "not_a_deal"


class CarveOutPotential(str, Enum):
    """Carve-out opportunity potential."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class AnalyzedItem:
    """A news item with LLM-generated analysis."""
    news_item: NewsItem
    is_relevant: bool
    relevance_level: RelevanceLevel
    relevance_explanation: str
    deal_type: DealType
    category: NewsCategory
    related_portfolio_companies: list[str]
    related_competitors: list[str]
    related_sectors: list[str]
    carve_out_potential: CarveOutPotential
    carve_out_rationale: str | None
    key_entities: dict[str, str]  # {entity_name: entity_type}


@dataclass
class RelevanceAnalyzer:
    """Analyzes news items for relevance to SilverTree portfolio."""

    api_key: str
    model: str = "gemini-2.5-flash"

    def __post_init__(self) -> None:
        genai.configure(api_key=self.api_key)
        self.client = genai.GenerativeModel(self.model)

    async def analyze_item(
        self,
        item: NewsItem,
        portfolio_context: str,
    ) -> AnalyzedItem:
        """Analyze a single news item for relevance."""
        prompt = self._build_prompt(item, portfolio_context)

        try:
            response = self.client.generate_content(prompt)
            result = self._parse_response(response.text)
            return self._build_analyzed_item(item, result)
        except Exception as e:
            logger.error(f"Failed to analyze item {item.id}: {e}")
            return self._build_default_analyzed_item(item)

    async def analyze_batch(
        self,
        items: list[NewsItem],
        portfolio_context: str,
        on_progress: Any | None = None,
    ) -> list[AnalyzedItem]:
        """Analyze multiple news items."""
        results: list[AnalyzedItem] = []
        total = len(items)

        for i, item in enumerate(items):
            analyzed = await self.analyze_item(item, portfolio_context)
            results.append(analyzed)

            if on_progress:
                on_progress(i + 1, total)

        return results

    def _build_prompt(self, item: NewsItem, portfolio_context: str) -> str:
        return f"""Analyze this news item for relevance to SilverTree Equity, a private equity firm.

## Portfolio Context
{portfolio_context}

## News Item
Title: {item.title}
Source: {item.source}
URL: {item.source_url}
Date: {item.published_date.isoformat() if item.published_date else 'Unknown'}
Summary: {item.summary}

## Analysis Required
Respond with a JSON object containing:

{{
    "is_relevant": true/false,
    "relevance_level": "high" | "medium" | "low",
    "relevance_explanation": "1-2 sentences explaining WHY this matters to SilverTree",
    "deal_type": "ma_acquisition" | "ma_merger" | "divestiture" | "fundraising" | "ipo" | "partnership" | "product_launch" | "personnel_change" | "strategic_update" | "not_a_deal",
    "category": "ma_deal" | "fundraising" | "partnership" | "product_launch" | "personnel_change" | "strategic_update" | "other",
    "related_portfolio_companies": ["company names from portfolio that are mentioned or affected"],
    "related_competitors": ["competitor names mentioned"],
    "related_sectors": ["relevant sectors"],
    "carve_out_potential": "high" | "medium" | "low" | "none" | "not_applicable",
    "carve_out_rationale": "If M&A deal, explain potential carve-out opportunity or why none exists",
    "key_entities": {{"Entity Name": "acquirer/target/investor/company"}}
}}

Rules:
1. An item is relevant if it affects portfolio companies, their competitors, or their sectors
2. For M&A deals, ALWAYS assess carve-out potential - are there non-core business units that could be acquired separately?
3. Be specific in relevance explanations - mention specific portfolio companies or competitive dynamics
4. Carve-out indicators: "division", "unit", "non-core", "strategic review", "portfolio rationalization"

Respond ONLY with the JSON object, no other text."""

    def _parse_response(self, response_text: str) -> dict[str, Any]:
        """Parse LLM response JSON."""
        # Clean up response - extract JSON if wrapped in markdown
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return {}

    def _build_analyzed_item(
        self,
        item: NewsItem,
        result: dict[str, Any],
    ) -> AnalyzedItem:
        """Build AnalyzedItem from parsed LLM response."""
        return AnalyzedItem(
            news_item=item,
            is_relevant=result.get("is_relevant", False),
            relevance_level=RelevanceLevel(result.get("relevance_level", "low")),
            relevance_explanation=result.get("relevance_explanation", ""),
            deal_type=DealType(result.get("deal_type", "not_a_deal")),
            category=NewsCategory(result.get("category", "other")),
            related_portfolio_companies=result.get("related_portfolio_companies", []),
            related_competitors=result.get("related_competitors", []),
            related_sectors=result.get("related_sectors", []),
            carve_out_potential=CarveOutPotential(
                result.get("carve_out_potential", "not_applicable")
            ),
            carve_out_rationale=result.get("carve_out_rationale"),
            key_entities=result.get("key_entities", {}),
        )

    def _build_default_analyzed_item(self, item: NewsItem) -> AnalyzedItem:
        """Build default AnalyzedItem when analysis fails."""
        return AnalyzedItem(
            news_item=item,
            is_relevant=False,
            relevance_level=RelevanceLevel.LOW,
            relevance_explanation="Analysis failed",
            deal_type=DealType.NOT_A_DEAL,
            category=NewsCategory.OTHER,
            related_portfolio_companies=[],
            related_competitors=[],
            related_sectors=[],
            carve_out_potential=CarveOutPotential.NOT_APPLICABLE,
            carve_out_rationale=None,
            key_entities={},
        )


def build_portfolio_context(
    companies: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
) -> str:
    """Build portfolio context string for LLM prompts."""
    lines = ["SilverTree Equity Portfolio Companies:"]

    for company in companies:
        name = company.get("name", "")
        context = company.get("company_context", "")
        sector = company.get("sector", "")
        competitors = company.get("competitors_candidate", [])

        lines.append(f"\n- {name}")
        if context:
            lines.append(f"  Description: {context}")
        if sector:
            lines.append(f"  Sector: {sector}")
        if competitors:
            lines.append(f"  Key Competitors: {', '.join(competitors[:5])}")

    lines.append("\n\nCompetitor Clusters to Monitor:")
    for cluster in clusters:
        name = cluster.get("name", "")
        what_it_is = cluster.get("what_it_is", "")
        canonical = cluster.get("canonical_competitors_seed", [])

        lines.append(f"\n- {name}")
        if what_it_is:
            lines.append(f"  {what_it_is}")
        if canonical:
            lines.append(f"  Key players: {', '.join(canonical[:5])}")

    return "\n".join(lines)
