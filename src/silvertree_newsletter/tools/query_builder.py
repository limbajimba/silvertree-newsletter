"""Query builder for portfolio, competitor, and industry searches.

Generates natural language queries optimized for Perplexity's AI search.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Iterable

from silvertree_newsletter.models.schemas import (
    CompanyProfile,
    CompetitorCluster,
    QueryType,
    SearchContextSize,
    SearchQuery,
)

DEFAULT_DEAL_TERMS = [
    "acquisition",
    "merger",
    "funding",
    "investment",
    "strategic partnership",
    "divestiture",
    "carve-out",
]
DEFAULT_ACTIVITY_TERMS = [
    "product launch",
    "new partnership",
    "executive appointment",
    "expansion",
    "contract win",
]


def _recency_filter_from_days(days: int) -> str:
    """Calculate recency filter from lookback days."""
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    if days <= 31:
        return "month"
    return "year"


def _search_after_date_from_days(days: int) -> str:
    """Calculate search_after_date from lookback days.

    Returns date in MM/DD/YYYY format as required by Perplexity API.
    """
    target_date = datetime.now(timezone.utc) - timedelta(days=days)
    return target_date.strftime("%m/%d/%Y")


def _natural_list(terms: list[str], max_terms: int = 4) -> str:
    """Convert a list of terms to natural language.

    Examples:
        ["A"] -> "A"
        ["A", "B"] -> "A or B"
        ["A", "B", "C"] -> "A, B, or C"
    """
    cleaned = _dedupe_terms(terms)[:max_terms]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} or {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", or {cleaned[-1]}"


def _dedupe_terms(terms: Iterable[str]) -> list[str]:
    """Remove duplicates while preserving order."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for term in terms:
        if not term:
            continue
        normalized = term.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(normalized)
    return cleaned


def _collect_competitors(company: CompanyProfile, max_competitors: int) -> list[str]:
    """Collect competitors, prioritizing direct then indirect lists."""
    direct = _dedupe_terms(company.direct_competitors)
    indirect = _dedupe_terms(company.indirect_competitors)
    if direct or indirect:
        combined = _dedupe_terms(direct + indirect)
    else:
        combined = _dedupe_terms(company.competitors_candidate)
    return combined[:max_competitors]


def build_search_queries(
    companies: list[CompanyProfile],
    clusters: list[CompetitorCluster],
    lookback_days: int,
    *,
    max_company_terms: int = 3,
    max_competitors: int = 8,
    max_event_terms: int = 4,
    search_context_size: SearchContextSize = SearchContextSize.MEDIUM,
) -> list[SearchQuery]:
    """Generate natural language search queries for Perplexity.

    Creates queries for:
    - Portfolio company news (deals + activity)
    - GP Bullhound coverage
    - Competitor movements
    - Industry trends
    """
    queries: list[SearchQuery] = []
    created_at = datetime.now(timezone.utc)
    cluster_lookup = {cluster.cluster_id: cluster for cluster in clusters}

    recency_filter = _recency_filter_from_days(lookback_days)
    search_after_date = _search_after_date_from_days(lookback_days)

    for company in companies:
        seeds = company.search_query_seeds or {}

        # Get company names/aliases
        company_names = _dedupe_terms(
            [company.name] + company.aliases + seeds.get("company_terms", [])
        )[:max_company_terms]
        primary_name = company_names[0] if company_names else company.name

        # Get search terms
        deal_terms = seeds.get("deal_terms", []) or DEFAULT_DEAL_TERMS
        product_terms = seeds.get("product_terms", []) or DEFAULT_ACTIVITY_TERMS

        # Query 1: Portfolio company - M&A and deals
        deal_query = _build_portfolio_deal_query(
            company_name=primary_name,
            deal_terms=deal_terms[:max_event_terms],
            sector=company.sector,
        )
        queries.append(
            _make_query(
                query_text=deal_query,
                query_type=QueryType.PORTFOLIO,
                related_company=company.name,
                related_sector=company.sector,
                created_at=created_at,
                recency_filter=recency_filter,
                search_after_date=search_after_date,
                search_context_size=search_context_size,
            )
        )

        # Query 2: Portfolio company - Product and activity news
        activity_query = _build_portfolio_activity_query(
            company_name=primary_name,
            product_terms=product_terms[:max_event_terms],
            context=company.company_context,
        )
        queries.append(
            _make_query(
                query_text=activity_query,
                query_type=QueryType.PORTFOLIO,
                related_company=company.name,
                related_sector=company.sector,
                created_at=created_at,
                recency_filter=recency_filter,
                search_after_date=search_after_date,
                search_context_size=search_context_size,
            )
        )

        # Query 3: GP Bullhound coverage
        gp_query = _build_gp_bullhound_query(
            company_name=primary_name,
            sector=company.sector,
        )
        queries.append(
            _make_query(
                query_text=gp_query,
                query_type=QueryType.GP_BULLHOUND,
                related_company=company.name,
                related_sector=company.sector,
                created_at=created_at,
                domain_filter=["gpbullhound.com"],
                recency_filter=recency_filter,
                search_after_date=search_after_date,
                search_context_size=search_context_size,
            )
        )

        # Queries 4+: Competitor news
        competitors = _collect_competitors(company, max_competitors)
        for competitor in competitors:
            competitor_query = _build_competitor_query(
                competitor_name=competitor,
                deal_terms=deal_terms[:max_event_terms],
                sector=company.sector,
            )
            queries.append(
                _make_query(
                    query_text=competitor_query,
                    query_type=QueryType.COMPETITOR,
                    related_company=company.name,
                    related_sector=company.sector,
                    created_at=created_at,
                    recency_filter=recency_filter,
                    search_after_date=search_after_date,
                    search_context_size=search_context_size,
                )
            )

        # Industry/cluster queries
        cluster = cluster_lookup.get(company.cluster_id or "")
        if cluster:
            buckets = cluster.search_keyword_buckets or {}

            # Industry keywords
            industry_keywords = _dedupe_terms(
                company.competitor_cluster_tags + buckets.get("product", [])
            )[:max_event_terms]

            # Event terms from cluster
            event_terms = buckets.get("events", []) or DEFAULT_DEAL_TERMS

            if industry_keywords:
                # Industry M&A query
                industry_deal_query = _build_industry_deal_query(
                    keywords=industry_keywords,
                    event_terms=event_terms[:max_event_terms],
                    cluster_description=cluster.what_it_is,
                )
                queries.append(
                    _make_query(
                        query_text=industry_deal_query,
                        query_type=QueryType.INDUSTRY,
                        related_company=company.name,
                        related_sector=company.sector,
                        created_at=created_at,
                        recency_filter=recency_filter,
                        search_after_date=search_after_date,
                        search_context_size=search_context_size,
                    )
                )

                # Industry signals query (commercial + leadership)
                signal_terms = _dedupe_terms(
                    buckets.get("commercial_signals", [])
                    + buckets.get("leadership", [])
                )[:max_event_terms]

                if signal_terms:
                    industry_signal_query = _build_industry_signal_query(
                        keywords=industry_keywords,
                        signal_terms=signal_terms,
                        cluster_description=cluster.what_it_is,
                    )
                    queries.append(
                        _make_query(
                            query_text=industry_signal_query,
                            query_type=QueryType.INDUSTRY,
                            related_company=company.name,
                            related_sector=company.sector,
                            created_at=created_at,
                            recency_filter=recency_filter,
                            search_after_date=search_after_date,
                            search_context_size=search_context_size,
                        )
                    )

    return queries


def build_source_queries(
    domains: list[str],
    lookback_days: int,
    *,
    max_domains: int = 10,
    search_context_size: SearchContextSize = SearchContextSize.MEDIUM,
) -> list[SearchQuery]:
    """Build queries for trusted source domains."""
    queries: list[SearchQuery] = []
    created_at = datetime.now(timezone.utc)

    recency_filter = _recency_filter_from_days(lookback_days)
    search_after_date = _search_after_date_from_days(lookback_days)

    for domain in _dedupe_terms(domains)[:max_domains]:
        query_text = _build_source_query(domain)
        queries.append(
            _make_query(
                query_text=query_text,
                query_type=QueryType.INDUSTRY,
                related_company=None,
                related_sector=f"source:{domain}",
                created_at=created_at,
                domain_filter=[domain],
                recency_filter=recency_filter,
                search_after_date=search_after_date,
                search_context_size=search_context_size,
            )
        )

    return queries


# =============================================================================
# Natural Language Query Templates
# =============================================================================


def _build_portfolio_deal_query(
    company_name: str,
    deal_terms: list[str],
    sector: str | None,
) -> str:
    """Build query for portfolio company M&A/deal news."""
    events = _natural_list(deal_terms)
    sector_context = f" in {sector}" if sector else ""
    return f"Latest news about {company_name} {events}{sector_context}"


def _build_portfolio_activity_query(
    company_name: str,
    product_terms: list[str],
    context: str | None,
) -> str:
    """Build query for portfolio company product/activity news."""
    activities = _natural_list(product_terms)
    if context:
        return f"{company_name} {activities} - {context}"
    return f"Recent {company_name} announcements about {activities}"


def _build_gp_bullhound_query(
    company_name: str,
    sector: str | None,
) -> str:
    """Build query for GP Bullhound coverage."""
    if sector:
        return f"{company_name} {sector} deals investment banking coverage"
    return f"{company_name} M&A deals investment research"


def _build_competitor_query(
    competitor_name: str,
    deal_terms: list[str],
    sector: str | None,
) -> str:
    """Build query for competitor news."""
    events = _natural_list(deal_terms)
    sector_context = f" in {sector}" if sector else ""
    return f"{competitor_name} news {events}{sector_context}"


def _build_industry_deal_query(
    keywords: list[str],
    event_terms: list[str],
    cluster_description: str | None,
) -> str:
    """Build query for industry M&A/deal news."""
    industry = _natural_list(keywords, max_terms=3)
    events = _natural_list(event_terms)
    if cluster_description:
        return f"{industry} industry news: {events}. {cluster_description}"
    return f"{industry} market news about {events}"


def _build_industry_signal_query(
    keywords: list[str],
    signal_terms: list[str],
    cluster_description: str | None,
) -> str:
    """Build query for industry commercial signals."""
    industry = _natural_list(keywords, max_terms=3)
    signals = _natural_list(signal_terms)
    if cluster_description:
        return f"{industry} announcements: {signals}. {cluster_description}"
    return f"Latest {industry} news about {signals}"


def _build_source_query(domain: str) -> str:
    """Build query for trusted source domain."""
    return "Recent M&A deals, funding rounds, acquisitions, partnerships, and major announcements"


# =============================================================================
# Helper Functions
# =============================================================================


def _make_query(
    *,
    query_text: str,
    query_type: QueryType,
    related_company: str | None,
    related_sector: str | None,
    created_at: datetime,
    domain_filter: list[str] | None = None,
    recency_filter: str = "week",
    search_after_date: str | None = None,
    search_context_size: SearchContextSize = SearchContextSize.MEDIUM,
) -> SearchQuery:
    """Create a SearchQuery with a unique ID."""
    query_id = hashlib.sha256(
        f"{query_type}:{related_company}:{query_text}".encode("utf-8")
    ).hexdigest()
    return SearchQuery(
        id=query_id,
        query_text=query_text,
        query_type=query_type,
        related_company=related_company,
        related_sector=related_sector,
        domain_filter=domain_filter,
        recency_filter=recency_filter,
        search_after_date=search_after_date,
        search_context_size=search_context_size,
        created_at=created_at,
    )
