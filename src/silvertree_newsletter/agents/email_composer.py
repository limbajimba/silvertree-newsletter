"""Email Composer Agent - Assembles the weekly newsletter.

This agent takes all analyzed items and composes them into a
professional PE-grade weekly newsletter email.

Sections:
1. Executive Summary (key themes of the week)
2. Portfolio Company Signals
3. Competitive Cluster Signals
4. Major Deals & Market Activity
5. Carve-Out Opportunities (highlighted)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict
from urllib.parse import urlparse

import google.generativeai as genai

from silvertree_newsletter.workflow.state import (
    AnalyzedItem,
    CarveOutOpportunity,
    Newsletter,
    NewsletterSection,
    NewsletterItem,
    NewsletterGroup,
    SourceLink,
    ItemCategory,
    DealType,
)
from silvertree_newsletter.config import settings
from silvertree_newsletter.tools.company_context_loader import load_company_context
from silvertree_newsletter.tools.item_grouping import build_company_lookups, resolve_portfolio_company, resolve_cluster

logger = logging.getLogger(__name__)


# =============================================================================
# EMAIL COMPOSER PROMPT
# =============================================================================

EXECUTIVE_SUMMARY_PROMPT = """You are writing the executive summary for SilverTree Equity's weekly M&A and Market Signals newsletter.

## This Week's News Items:
{news_summary}

## Carve-Out Opportunities Flagged:
{carve_out_summary}

## Your Task:
Write a concise executive summary (3-5 sentences) that:
1. Highlights the most significant developments of the week
2. Calls out any portfolio company news
3. Flags key competitive threats
4. Highlights any carve-out opportunities worth immediate attention

Write in a professional, direct style suitable for PE partners.
No bullet points - flowing prose.
Only reference facts present in the provided items. Do not introduce new events.

Respond with ONLY the executive summary text, no JSON or formatting."""


FULL_COMPOSE_PROMPT = """You are composing the full weekly SilverTree Equity M&A and Market Signals newsletter.

Use ONLY the provided items and carve-out data. Do NOT invent facts or sources.
Deduplicate items that refer to the same event by merging them and listing multiple source_item_ids.
Keep the newsletter concise and high-signal.

Rules:
- Use only source_item_ids from the provided items list.
- Do not repeat the same source_item_id across sections.
- Prefer higher signal_score items when filtering for length.
- If data is missing, write concise and factual summaries.
- Include an "impact_on_silvertree" line for every item.

Output JSON only with this schema:
{
  "subject": "string",
  "executive_summary": "3-5 sentences",
  "sections": {
    "portfolio": {
      "title": "Portfolio Company Signals",
      "groups": [
        {
          "name": "Portfolio Company Name",
          "items": [
            {
              "headline": "string",
              "summary": "1-2 sentences",
              "impact_on_silvertree": "1 sentence",
              "category": "portfolio" | "competitor" | "major_deal" | "industry",
              "deal_type": "ma_acquisition" | "ma_merger" | "divestiture" | "fundraising" | "ipo" | "partnership" | "product_launch" | "personnel_change" | "strategic_update" | "not_a_deal",
              "signal_score": 0-100,
              "portfolio_company": "Company Name or null",
              "cluster": "Cluster name or null",
              "source_item_ids": ["id1", "id2"]
            }
          ]
        }
      ]
    },
    "competitive": { "title": "Competitive Cluster Signals", "groups": [ ... ] },
    "deals": { "title": "Major Deals & Market Activity", "groups": [ ... ] }
  }
}
"""

CARVE_OUT_MERGE_PROMPT = """You are deduplicating carve-out opportunities for a private equity newsletter.

Merge entries that refer to the same underlying deal or target company.
Keep the output concise and high-signal. Do NOT invent facts.

Output JSON only as a list with this schema:
[
  {
    "canonical_id": "source_item_id",
    "merged_ids": ["id1", "id2"],
    "target_company": "string",
    "potential_units": ["unit1", "unit2"],
    "priority": "high" | "medium",
    "strategic_fit_rationale": "1-2 sentences",
    "recommended_action": "string"
  }
]

Rules:
- canonical_id and merged_ids must reference input ids only.
- Every input id must appear at most once across all merged_ids.
- Use the highest priority among merged entries.
"""


# =============================================================================
# HTML TEMPLATE
# =============================================================================

EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SilverTree Weekly M&A Signals</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .header {{
            border-bottom: 3px solid #1a5f2a;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .header h1 {{
            color: #1a5f2a;
            margin: 0;
            font-size: 24px;
        }}
        .header .date {{
            color: #666;
            font-size: 14px;
            margin-top: 5px;
        }}
        .executive-summary {{
            background: #f8f9fa;
            border-left: 4px solid #1a5f2a;
            padding: 20px;
            margin-bottom: 30px;
        }}
        .executive-summary h2 {{
            color: #1a5f2a;
            margin-top: 0;
            font-size: 18px;
        }}
        .section {{
            margin-bottom: 30px;
        }}
        .section h2 {{
            color: #1a5f2a;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 10px;
            font-size: 18px;
        }}
        .news-item {{
            padding: 15px;
            margin-bottom: 15px;
            background: #fafafa;
            border-radius: 4px;
            border-left: 3px solid #ddd;
        }}
        .news-item.portfolio {{
            border-left-color: #1a5f2a;
        }}
        .news-item.competitor {{
            border-left-color: #e67e22;
        }}
        .news-item.deal {{
            border-left-color: #3498db;
        }}
        .news-item.industry {{
            border-left-color: #6c757d;
        }}
        .news-item.carveout {{
            border-left-color: #e74c3c;
            background: #fef5f5;
        }}
        .news-item h3 {{
            margin: 0 0 10px 0;
            font-size: 16px;
        }}
        .news-item h3 a {{
            color: #333;
            text-decoration: none;
        }}
        .news-item h3 a:hover {{
            color: #1a5f2a;
        }}
        .news-item .meta {{
            font-size: 12px;
            color: #666;
            margin-bottom: 10px;
        }}
        .news-item .why-it-matters {{
            font-size: 14px;
            color: #444;
        }}
        .news-item .impact {{
            margin-top: 8px;
            font-size: 13px;
            color: #2c3e50;
        }}
        .group {{
            margin-bottom: 20px;
        }}
        .group h3 {{
            margin: 0 0 10px 0;
            font-size: 15px;
            color: #1a5f2a;
        }}
        .carveout-alert {{
            background: #fef5f5;
            border: 2px solid #e74c3c;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 30px;
        }}
        .carveout-alert h2 {{
            color: #e74c3c;
            margin-top: 0;
        }}
        .carveout-item {{
            background: white;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 10px;
        }}
        .priority-high {{
            border-left: 4px solid #e74c3c;
        }}
        .priority-medium {{
            border-left: 4px solid #e67e22;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #e0e0e0;
            font-size: 12px;
            color: #666;
            text-align: center;
        }}
        .tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: bold;
            margin-right: 5px;
        }}
        .tag-portfolio {{ background: #d4edda; color: #155724; }}
        .tag-competitor {{ background: #fff3cd; color: #856404; }}
        .tag-deal {{ background: #cce5ff; color: #004085; }}
        .tag-industry {{ background: #e2e3e5; color: #383d41; }}
        .tag-carveout {{ background: #f8d7da; color: #721c24; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌲 SilverTree Weekly M&A Signals</h1>
            <div class="date">Week of {period_start} - {period_end}</div>
        </div>

        <div class="executive-summary">
            <h2>Executive Summary</h2>
            <p>{executive_summary}</p>
        </div>

        {carveout_section}

        {portfolio_section}

        {competitive_cluster_section}

        {deals_section}

        <div class="footer">
            <p>Generated automatically by SilverTree M&A Signals Tracker</p>
            <p>{total_items} items processed | {relevant_items} relevant items</p>
        </div>
    </div>
</body>
</html>
"""


# =============================================================================
# EMAIL COMPOSER AGENT
# =============================================================================

@dataclass
class EmailComposerAgent:
    """Composes the weekly newsletter email."""

    api_key: str
    model: str = "gemini-2.5-flash"

    def __post_init__(self) -> None:
        genai.configure(api_key=self.api_key)
        self.client = genai.GenerativeModel(self.model)

    def compose_newsletter(
        self,
        analyzed_items: list[AnalyzedItem],
        carve_outs: list[CarveOutOpportunity],
        total_processed: int,
    ) -> tuple[Newsletter, str]:
        """Compose the complete newsletter."""
        json_path = Path(settings.company_data_path)
        if not json_path.exists():
            json_path = Path(__file__).parent.parent.parent.parent / settings.company_data_path
        companies, clusters = load_company_context(json_path)
        company_lookup, cluster_lookup = build_company_lookups(companies, clusters)

        merged_carve_outs = self._merge_carve_outs(carve_outs)

        try:
            newsletter = self._compose_with_llm(
                analyzed_items,
                merged_carve_outs,
                total_processed=total_processed,
                company_lookup=company_lookup,
                cluster_lookup=cluster_lookup,
            )
        except Exception as exc:
            logger.warning(f"LLM newsletter composition failed, falling back: {exc}")
            newsletter = self._compose_with_template(
                analyzed_items,
                merged_carve_outs,
                total_processed=total_processed,
                company_lookup=company_lookup,
                cluster_lookup=cluster_lookup,
            )

        # Render HTML
        html = self._render_html(
            newsletter,
            merged_carve_outs,
            company_lookup=company_lookup,
            cluster_lookup=cluster_lookup,
        )

        return newsletter, html

    def _merge_carve_outs(
        self,
        carve_outs: list[CarveOutOpportunity],
    ) -> list[CarveOutOpportunity]:
        if not carve_outs:
            return []

        hydrated = [_ensure_carve_out_sources(co) for co in carve_outs]
        if len(hydrated) <= 1:
            return hydrated
        if not self.api_key:
            return _heuristic_merge_carve_outs(hydrated)

        payload = []
        for co in hydrated:
            raw = co.source_item.triaged_item.raw_item
            payload.append(
                {
                    "id": raw.id,
                    "target_company": co.target_company,
                    "potential_units": co.potential_units,
                    "priority": co.priority,
                    "strategic_fit_rationale": co.strategic_fit_rationale,
                    "recommended_action": co.recommended_action,
                    "source_url": raw.source_url,
                    "headline": raw.title,
                }
            )

        prompt = (
            f"{CARVE_OUT_MERGE_PROMPT}\n\n"
            f"Carve-outs (JSON):\n{json.dumps(payload, indent=2)}"
        )

        try:
            response = self.client.generate_content(prompt)
            result = _parse_json(response.text)
            if not isinstance(result, list):
                raise ValueError("Carve-out merge did not return a JSON list")
            merged = _apply_carve_out_merge(result, hydrated)
            logger.info(
                "Carve-out merge complete",
                extra={"original": len(carve_outs), "merged": len(merged)},
            )
            return merged
        except Exception as exc:
            logger.warning(f"Carve-out merge failed, using heuristic: {exc}")
            return _heuristic_merge_carve_outs(hydrated)

    def _group_by_category(
        self,
        items: list[AnalyzedItem],
    ) -> dict[ItemCategory, list[AnalyzedItem]]:
        """Group analyzed items by their category."""
        grouped: dict[ItemCategory, list[AnalyzedItem]] = defaultdict(list)
        for item in items:
            grouped[item.triaged_item.category].append(item)
        return grouped

    def _generate_executive_summary(
        self,
        items: list[AnalyzedItem],
        carve_outs: list[CarveOutOpportunity],
    ) -> str:
        """Generate executive summary using LLM."""
        # Build news summary
        news_lines = []
        ranked_items = sorted(items, key=lambda i: i.signal_score, reverse=True)
        for item in ranked_items[:10]:
            news_lines.append(
                f"- [{item.triaged_item.category.value}] {item.triaged_item.raw_item.title}: "
                f"{item.why_it_matters}"
            )
        news_summary = "\n".join(news_lines) if news_lines else "No significant news this week."

        # Build carve-out summary
        carve_out_lines = []
        for co in carve_outs:
            carve_out_lines.append(
                f"- {co.target_company}: {', '.join(co.potential_units)} ({co.priority} priority)"
            )
        carve_out_summary = "\n".join(carve_out_lines) if carve_out_lines else "No carve-out opportunities identified."

        prompt = EXECUTIVE_SUMMARY_PROMPT.format(
            news_summary=news_summary,
            carve_out_summary=carve_out_summary,
        )

        try:
            response = self.client.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"Failed to generate executive summary: {e}")
            return "Executive summary generation failed. Please review items below."

    def _compose_with_llm(
        self,
        analyzed_items: list[AnalyzedItem],
        carve_outs: list[CarveOutOpportunity],
        *,
        total_processed: int,
        company_lookup: dict[str, object],
        cluster_lookup: dict[str, object],
    ) -> Newsletter:
        """Compose the newsletter using an LLM for full structure and dedupe."""
        items_payload = []
        for item in analyzed_items:
            portfolio_company = resolve_portfolio_company(item, company_lookup)
            cluster = resolve_cluster(item, company_lookup, cluster_lookup)
            raw = item.triaged_item.raw_item
            items_payload.append(
                {
                    "id": raw.id,
                    "title": raw.title,
                    "summary": raw.summary,
                    "source": raw.source,
                    "url": raw.source_url,
                    "published_date": raw.published_date.isoformat() if raw.published_date else None,
                    "category": item.triaged_item.category.value,
                    "deal_type": item.triaged_item.deal_type.value,
                    "portfolio_company": portfolio_company,
                    "cluster": cluster,
                    "why_it_matters": item.why_it_matters,
                    "impact_on_silvertree": item.impact_on_silvertree or item.triaged_item.triage_reason,
                    "signal_score": item.signal_score,
                    "evidence": item.evidence,
                }
            )

        carve_out_payload = [
            {
                "source_item_id": co.source_item.triaged_item.raw_item.id,
                "target_company": co.target_company,
                "potential_units": co.potential_units,
                "priority": co.priority,
                "source_url": co.source_item.triaged_item.raw_item.source_url,
            }
            for co in carve_outs
        ]

        max_competitive = settings.max_competitor_items + settings.max_industry_items
        max_total = settings.max_portfolio_items + max_competitive + settings.max_deal_items
        constraints = (
            f"Constraints: max_total_items={max_total}, "
            f"portfolio_items<= {settings.max_portfolio_items}, "
            f"competitive_items<= {max_competitive}, "
            f"deal_items<= {settings.max_deal_items}."
        )

        prompt = (
            f"{FULL_COMPOSE_PROMPT}\n\n{constraints}\n\n"
            f"Items (JSON):\n{json.dumps(items_payload, indent=2)}\n\n"
            f"Carve-outs (JSON):\n{json.dumps(carve_out_payload, indent=2)}"
        )

        response = self.client.generate_content(prompt)
        result = _parse_json(response.text)

        if not isinstance(result, dict):
            raise ValueError("LLM composition did not return a JSON object")

        item_lookup = {item.triaged_item.raw_item.id: item for item in analyzed_items}
        used_ids: set[str] = set()

        sections = result.get("sections", {}) or {}
        portfolio_section = self._build_section_from_llm(
            sections.get("portfolio"),
            default_title="Portfolio Company Signals",
            item_lookup=item_lookup,
            used_ids=used_ids,
        )
        competitive_section = self._build_section_from_llm(
            sections.get("competitive"),
            default_title="Competitive Cluster Signals",
            item_lookup=item_lookup,
            used_ids=used_ids,
        )
        deals_section = self._build_section_from_llm(
            sections.get("deals"),
            default_title="Major Deals & Market Activity",
            item_lookup=item_lookup,
            used_ids=used_ids,
        )

        if not (portfolio_section.items or competitive_section.items or deals_section.items):
            raise ValueError("LLM composition returned no usable items")

        executive_summary = _coerce_text(result.get("executive_summary")) or self._generate_executive_summary(
            analyzed_items, carve_outs
        )

        subject = _coerce_text(result.get("subject"))
        now = datetime.now(timezone.utc)
        subject = subject or f"SilverTree Weekly M&A Signals - {now.strftime('%B %d, %Y')}"

        carve_out_section = self._build_carve_out_section(carve_outs) if carve_outs else None

        logger.info(
            "LLM composed newsletter",
            extra={
                "selected_items": len(used_ids),
                "total_items": len(analyzed_items),
                "portfolio": len(portfolio_section.items),
                "competitive": len(competitive_section.items),
                "deals": len(deals_section.items),
            },
        )

        return Newsletter(
            subject=subject,
            generated_date=now,
            period_start=now - timedelta(days=7),
            period_end=now,
            executive_summary=executive_summary,
            portfolio_section=portfolio_section,
            competitive_cluster_section=competitive_section,
            deals_section=deals_section,
            carve_out_section=carve_out_section,
            total_items_processed=total_processed,
            total_relevant_items=len(analyzed_items),
        )

    def _compose_with_template(
        self,
        analyzed_items: list[AnalyzedItem],
        carve_outs: list[CarveOutOpportunity],
        *,
        total_processed: int,
        company_lookup: dict[str, object],
        cluster_lookup: dict[str, object],
    ) -> Newsletter:
        """Fallback deterministic composition if LLM fails."""
        grouped = self._group_by_category(analyzed_items)
        executive_summary = self._generate_executive_summary(analyzed_items, carve_outs)

        portfolio_items = [
            self._build_newsletter_item(item, company_lookup, cluster_lookup)
            for item in grouped.get(ItemCategory.PORTFOLIO, [])
        ]
        competitive_items = [
            self._build_newsletter_item(item, company_lookup, cluster_lookup)
            for item in grouped.get(ItemCategory.COMPETITOR, []) + grouped.get(ItemCategory.INDUSTRY, [])
        ]
        deal_items = [
            self._build_newsletter_item(item, company_lookup, cluster_lookup)
            for item in grouped.get(ItemCategory.MAJOR_DEAL, [])
        ]

        portfolio_section = self._build_grouped_section(
            "Portfolio Company Signals",
            portfolio_items,
            lambda item: item.portfolio_company,
        )
        competitive_section = self._build_grouped_section(
            "Competitive Cluster Signals",
            competitive_items,
            lambda item: item.cluster,
        )
        deals_section = self._build_grouped_section(
            "Major Deals & Market Activity",
            deal_items,
            lambda item: item.cluster,
        )

        now = datetime.now(timezone.utc)
        carve_out_section = self._build_carve_out_section(carve_outs) if carve_outs else None

        return Newsletter(
            subject=f"SilverTree Weekly M&A Signals - {now.strftime('%B %d, %Y')}",
            generated_date=now,
            period_start=now - timedelta(days=7),
            period_end=now,
            executive_summary=executive_summary,
            portfolio_section=portfolio_section,
            competitive_cluster_section=competitive_section,
            deals_section=deals_section,
            carve_out_section=carve_out_section,
            total_items_processed=total_processed,
            total_relevant_items=len(analyzed_items),
        )

    def _build_grouped_section(
        self,
        title: str,
        items: list[NewsletterItem],
        group_fn,
    ) -> NewsletterSection:
        groups = _group_items(items, group_fn)
        return NewsletterSection(
            title=title,
            items=items,
            groups=groups,
            section_summary=None,
        )

    def _build_newsletter_item(
        self,
        item: AnalyzedItem,
        company_lookup: dict[str, object],
        cluster_lookup: dict[str, object],
    ) -> NewsletterItem:
        raw = item.triaged_item.raw_item
        portfolio_company = resolve_portfolio_company(item, company_lookup)
        cluster = resolve_cluster(item, company_lookup, cluster_lookup)
        impact = item.impact_on_silvertree or item.triaged_item.triage_reason or ""
        sources = [
            SourceLink(
                title=raw.title,
                url=raw.source_url,
                source=raw.source,
            )
        ]
        sources = _dedupe_source_links(sources)
        return NewsletterItem(
            headline=raw.title,
            summary=item.why_it_matters,
            impact_on_silvertree=impact,
            category=item.triaged_item.category,
            deal_type=item.triaged_item.deal_type,
            portfolio_company=portfolio_company,
            cluster=cluster,
            signal_score=item.signal_score,
            primary_date=raw.published_date,
            sources=sources,
            source_item_ids=[raw.id],
        )

    def _build_section_from_llm(
        self,
        section_data: dict | None,
        *,
        default_title: str,
        item_lookup: dict[str, AnalyzedItem],
        used_ids: set[str],
    ) -> NewsletterSection:
        if not section_data:
            return NewsletterSection(title=default_title)

        title = _coerce_text(section_data.get("title")) or default_title
        groups_data = section_data.get("groups", []) or []
        groups: list[NewsletterGroup] = []
        section_items: list[NewsletterItem] = []

        for group in groups_data:
            group_name = _coerce_text(group.get("name")) or "Other"
            items_data = group.get("items", []) or []
            group_items: list[NewsletterItem] = []

            for item_data in items_data:
                ids = item_data.get("source_item_ids") or []
                ids = [item_id for item_id in ids if item_id in item_lookup and item_id not in used_ids]
                if not ids:
                    continue
                used_ids.update(ids)
                source_items = [item_lookup[item_id] for item_id in ids]
                newsletter_item = _build_item_from_llm(item_data, source_items, group_name)
                group_items.append(newsletter_item)
                section_items.append(newsletter_item)

            if group_items:
                groups.append(NewsletterGroup(name=group_name, items=group_items))

        return NewsletterSection(
            title=title,
            items=section_items,
            groups=groups,
            section_summary=_coerce_text(section_data.get("section_summary")),
        )

    def _build_carve_out_section(
        self,
        carve_outs: list[CarveOutOpportunity],
    ) -> NewsletterSection:
        """Build the carve-out opportunities section."""
        items: list[NewsletterItem] = []
        for co in carve_outs:
            source_items = co.source_items or [co.source_item]
            raw = source_items[0].triaged_item.raw_item
            impact = co.source_item.impact_on_silvertree or co.source_item.triaged_item.triage_reason or ""
            sources = [
                SourceLink(
                    title=item.triaged_item.raw_item.title,
                    url=item.triaged_item.raw_item.source_url,
                    source=item.triaged_item.raw_item.source,
                )
                for item in source_items
            ]
            sources = _dedupe_source_links(sources)
            items.append(
                NewsletterItem(
                    headline=raw.title,
                    summary=co.strategic_fit_rationale or co.source_item.why_it_matters,
                    impact_on_silvertree=impact,
                    category=co.source_item.triaged_item.category,
                    deal_type=co.source_item.triaged_item.deal_type,
                    portfolio_company=co.source_item.triaged_item.related_portfolio_company,
                    cluster=None,
                    signal_score=co.source_item.signal_score,
                    primary_date=raw.published_date,
                    sources=sources,
                    source_item_ids=[item.triaged_item.raw_item.id for item in source_items],
                )
            )
        return NewsletterSection(
            title="Carve-Out Opportunities",
            items=items,
            groups=_group_items(items, lambda item: item.portfolio_company),
            section_summary=f"{len(carve_outs)} potential carve-out opportunities identified.",
        )

    def _render_html(
        self,
        newsletter: Newsletter,
        carve_outs: list[CarveOutOpportunity],
        *,
        company_lookup: dict[str, object],
        cluster_lookup: dict[str, object],
    ) -> str:
        """Render newsletter to HTML."""
        # Render carve-out section
        carveout_html = ""
        if carve_outs:
            carveout_items = []
            for co in carve_outs:
                source_items = co.source_items or [co.source_item]
                source_links = [
                    SourceLink(
                        title=item.triaged_item.raw_item.title,
                        url=item.triaged_item.raw_item.source_url,
                        source=item.triaged_item.raw_item.source,
                    )
                    for item in source_items
                ]
                source_links = _dedupe_source_links(source_links)
                primary_source = source_links[0] if source_links else None
                source_link = (
                    f'<a href="{primary_source.url}" target="_blank">{primary_source.title}</a>'
                    if primary_source
                    else "Source"
                )
                source_label = primary_source.source if primary_source else "Source"
                extra_sources = ""
                if len(source_links) > 1:
                    extra_links = [
                        f'<a href="{src.url}" target="_blank">{src.source or "source"}</a>'
                        for src in source_links[1:4]
                    ]
                    extra_sources = f" | Also: {', '.join(extra_links)}"
                carveout_items.append(f"""
                <div class="carveout-item priority-{co.priority}">
                    <strong>{co.target_company}</strong>
                    <p><strong>Potential Units:</strong> {', '.join(co.potential_units)}</p>
                    <p><strong>Strategic Fit:</strong> {co.strategic_fit_rationale[:300]}...</p>
                    <p><strong>Source:</strong> {source_link} ({source_label}){extra_sources}</p>
                    <p><strong>Action:</strong> {co.recommended_action}</p>
                </div>
                """)
            carveout_html = f"""
            <div class="carveout-alert">
                <h2>🎯 Carve-Out Opportunities</h2>
                {''.join(carveout_items)}
            </div>
            """

        # Render sections
        portfolio_html = self._render_grouped_section(
            newsletter.portfolio_section,
            lambda item: item.portfolio_company,
        )
        competitive_html = self._render_grouped_section(
            newsletter.competitive_cluster_section,
            lambda item: item.cluster,
        )
        deals_html = self._render_grouped_section(
            newsletter.deals_section,
            lambda item: item.cluster,
        )

        return EMAIL_TEMPLATE.format(
            period_start=newsletter.period_start.strftime("%B %d"),
            period_end=newsletter.period_end.strftime("%B %d, %Y"),
            executive_summary=newsletter.executive_summary,
            carveout_section=carveout_html,
            portfolio_section=portfolio_html,
            competitive_cluster_section=competitive_html,
            deals_section=deals_html,
            total_items=newsletter.total_items_processed,
            relevant_items=newsletter.total_relevant_items,
        )

    def _render_grouped_section(
        self,
        section: NewsletterSection,
        group_fn,
    ) -> str:
        """Render a grouped section to HTML."""
        if not section.items and not section.groups:
            return ""

        groups = section.groups or _group_items(section.items, group_fn)
        group_order = sorted(
            groups,
            key=lambda group: max(i.signal_score for i in group.items) if group.items else 0,
            reverse=True,
        )

        groups_html = []
        for group in group_order:
            group_name = group.name
            group_items = group.items
            items_html = [self._render_item(item) for item in group_items]
            groups_html.append(f"""
            <div class="group">
                <h3>{group_name}</h3>
                {''.join(items_html)}
            </div>
            """)

        return f"""
        <div class="section">
            <h2>{section.title}</h2>
            {''.join(groups_html)}
        </div>
        """

    def _render_item(self, item: NewsletterItem) -> str:
        category_class = _category_class(item.category)
        impact_line = item.impact_on_silvertree or "Not specified."
        sources = _dedupe_source_links(item.sources or [])
        primary_link = sources[0] if sources else None
        title = item.headline
        link_html = f'<a href="{primary_link.url}" target="_blank">{title}</a>' if primary_link else title
        source_label = primary_link.source if primary_link else "Source"
        date_label = item.primary_date.strftime('%b %d') if item.primary_date else "Recent"
        extra_sources = ""
        if len(sources) > 1:
            extra_links = [
                f'<a href="{src.url}" target="_blank">{src.source or "source"}</a>'
                for src in sources[1:4]
            ]
            extra_sources = f" | Also: {', '.join(extra_links)}"
        return f"""
        <div class="news-item {category_class}">
            <h3>{link_html}</h3>
            <div class="meta">
                <span class="tag tag-{category_class}">{item.deal_type.value.replace('_', ' ').title()}</span>
                {source_label} | {date_label}{extra_sources}
            </div>
            <div class="why-it-matters">{item.summary}</div>
            <div class="impact"><strong>Impact on SilverTree:</strong> {impact_line}</div>
        </div>
        """


def _category_class(category: ItemCategory) -> str:
    if category == ItemCategory.PORTFOLIO:
        return "portfolio"
    if category == ItemCategory.COMPETITOR:
        return "competitor"
    if category == ItemCategory.MAJOR_DEAL:
        return "deal"
    return "industry"


def _parse_json(text: str) -> object:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
    return {}


def _coerce_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value)


def _coerce_int(value, default: int) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(100, score))


def _coerce_enum(enum_cls, value, default):
    if isinstance(value, enum_cls):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        value = normalized
    try:
        return enum_cls(value)
    except ValueError:
        return default


def _group_items(items: list[NewsletterItem], group_fn) -> list[NewsletterGroup]:
    grouped: dict[str, list[NewsletterItem]] = {}
    for item in items:
        key = _coerce_text(group_fn(item)) or "Other"
        grouped.setdefault(key, []).append(item)

    groups = []
    for group_name, group_items in grouped.items():
        groups.append(NewsletterGroup(name=group_name, items=group_items))
    return groups


def _ensure_carve_out_sources(co: CarveOutOpportunity) -> CarveOutOpportunity:
    if co.source_items:
        return co
    return co.model_copy(update={"source_items": [co.source_item]})


def _collect_source_items(carve_outs: list[CarveOutOpportunity]) -> list[AnalyzedItem]:
    seen: set[str] = set()
    collected: list[AnalyzedItem] = []
    for co in carve_outs:
        for item in (co.source_items or [co.source_item]):
            item_id = item.triaged_item.raw_item.id
            if item_id in seen:
                continue
            seen.add(item_id)
            collected.append(item)
    return collected


def _dedupe_text_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = _coerce_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


def _priority_rank(priority: str) -> int:
    return 2 if str(priority).lower() == "high" else 1


def _best_carve_out(carve_outs: list[CarveOutOpportunity]) -> CarveOutOpportunity:
    return max(
        carve_outs,
        key=lambda co: (_priority_rank(co.priority), co.source_item.signal_score),
    )


def _highest_priority(carve_outs: list[CarveOutOpportunity]) -> str:
    return "high" if any(co.priority == "high" for co in carve_outs) else "medium"


def _coerce_priority(value: str | None, fallback: str) -> str:
    if isinstance(value, str) and value.strip().lower() in {"high", "medium"}:
        return value.strip().lower()
    return fallback


def _apply_carve_out_merge(
    merged_payload: list[dict],
    carve_outs: list[CarveOutOpportunity],
) -> list[CarveOutOpportunity]:
    by_id = {co.source_item.triaged_item.raw_item.id: co for co in carve_outs}
    used_ids: set[str] = set()
    merged: list[CarveOutOpportunity] = []

    for entry in merged_payload:
        raw_ids = entry.get("merged_ids") or []
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        merged_ids = _dedupe_text_list(raw_ids if isinstance(raw_ids, list) else [])
        merged_ids = [item_id for item_id in merged_ids if item_id in by_id]
        canonical_id = entry.get("canonical_id")
        if canonical_id in by_id and canonical_id not in merged_ids:
            merged_ids = [canonical_id] + merged_ids
        if not merged_ids:
            continue

        group = [by_id[item_id] for item_id in merged_ids]
        primary = by_id[canonical_id] if canonical_id in by_id else _best_carve_out(group)
        source_items = _collect_source_items(group)
        priority = _coerce_priority(entry.get("priority"), _highest_priority(group))
        raw_units = entry.get("potential_units") or []
        if isinstance(raw_units, str):
            raw_units = [raw_units]
        raw_units = raw_units if isinstance(raw_units, list) else []
        potential_units = _dedupe_text_list(
            raw_units + [unit for co in group for unit in co.potential_units]
        )

        merged.append(
            CarveOutOpportunity(
                source_item=primary.source_item,
                source_items=source_items,
                target_company=_coerce_text(entry.get("target_company")) or primary.target_company,
                potential_units=potential_units or primary.potential_units,
                strategic_fit_rationale=_coerce_text(entry.get("strategic_fit_rationale")) or primary.strategic_fit_rationale,
                recommended_action=_coerce_text(entry.get("recommended_action")) or primary.recommended_action,
                priority=priority,
            )
        )
        used_ids.update(merged_ids)

    for co in carve_outs:
        item_id = co.source_item.triaged_item.raw_item.id
        if item_id not in used_ids:
            merged.append(_ensure_carve_out_sources(co))

    return merged


def _normalize_company_name(value: str | None) -> str:
    text = _coerce_text(value) or ""
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    text = re.sub(r"\b(inc|ltd|llc|plc|corp|corporation|group|holdings|company|co)\b", " ", text)
    return " ".join(text.split())


def _heuristic_merge_carve_outs(carve_outs: list[CarveOutOpportunity]) -> list[CarveOutOpportunity]:
    grouped: dict[str, list[CarveOutOpportunity]] = {}
    for co in carve_outs:
        key = _normalize_company_name(co.target_company)
        if not key:
            key = _normalize_company_name(co.source_item.triaged_item.raw_item.title)
        grouped.setdefault(key or co.target_company, []).append(co)

    merged: list[CarveOutOpportunity] = []
    for group in grouped.values():
        if len(group) == 1:
            merged.append(_ensure_carve_out_sources(group[0]))
            continue
        primary = _best_carve_out(group)
        source_items = _collect_source_items(group)
        potential_units = _dedupe_text_list([unit for co in group for unit in co.potential_units])
        merged.append(
            CarveOutOpportunity(
                source_item=primary.source_item,
                source_items=source_items,
                target_company=primary.target_company,
                potential_units=potential_units or primary.potential_units,
                strategic_fit_rationale=primary.strategic_fit_rationale,
                recommended_action=primary.recommended_action,
                priority=_highest_priority(group),
            )
        )

    return merged


def _domain_from_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc
    except ValueError:
        return ""


def _dedupe_source_links(sources: list[SourceLink]) -> list[SourceLink]:
    seen_urls: set[str] = set()
    seen_labels: set[str] = set()
    deduped: list[SourceLink] = []
    for source in sources:
        url = (source.url or "").strip()
        label = (source.source or _domain_from_url(url) or "source").strip()
        label_key = label.lower()
        if url and url in seen_urls:
            continue
        if label_key in seen_labels:
            continue
        if url:
            seen_urls.add(url)
        seen_labels.add(label_key)
        deduped.append(SourceLink(title=source.title, url=url, source=label))
    return deduped


def _build_item_from_llm(
    item_data: dict,
    source_items: list[AnalyzedItem],
    group_name: str,
) -> NewsletterItem:
    primary = source_items[0]
    raw = primary.triaged_item.raw_item
    fallback_score = max((item.signal_score for item in source_items), default=50)
    headline = _coerce_text(item_data.get("headline")) or raw.title
    summary = _coerce_text(item_data.get("summary")) or primary.why_it_matters
    impact = _coerce_text(item_data.get("impact_on_silvertree")) or primary.impact_on_silvertree or primary.triaged_item.triage_reason
    category = _coerce_enum(ItemCategory, item_data.get("category"), primary.triaged_item.category)
    deal_type = _coerce_enum(DealType, item_data.get("deal_type"), primary.triaged_item.deal_type)
    signal_score = _coerce_int(item_data.get("signal_score"), fallback_score)
    portfolio_company = _coerce_text(item_data.get("portfolio_company"))
    cluster = _coerce_text(item_data.get("cluster"))

    if category == ItemCategory.PORTFOLIO and not portfolio_company:
        portfolio_company = group_name
    if category in (ItemCategory.COMPETITOR, ItemCategory.INDUSTRY, ItemCategory.MAJOR_DEAL) and not cluster:
        cluster = group_name

    sources: list[SourceLink] = []
    primary_date = None
    for source_item in source_items:
        source_raw = source_item.triaged_item.raw_item
        sources.append(
            SourceLink(
                title=source_raw.title,
                url=source_raw.source_url,
                source=source_raw.source,
            )
        )
        if source_raw.published_date and (primary_date is None or source_raw.published_date > primary_date):
            primary_date = source_raw.published_date

    sources = _dedupe_source_links(sources)

    return NewsletterItem(
        headline=headline,
        summary=summary,
        impact_on_silvertree=impact,
        category=category,
        deal_type=deal_type,
        portfolio_company=portfolio_company,
        cluster=cluster,
        signal_score=signal_score,
        primary_date=primary_date,
        sources=sources,
        source_item_ids=[item.triaged_item.raw_item.id for item in source_items],
    )
