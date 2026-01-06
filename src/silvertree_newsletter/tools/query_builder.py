"""Query builder for portfolio, competitor, and industry searches."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterable

from silvertree_newsletter.models.schemas import (
    CompanyProfile,
    CompetitorCluster,
    QueryType,
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
    "press release",
    "announcement",
    "launch",
    "product",
    "partnership",
    "appoints",
    "CEO",
    "CFO",
]


def build_search_queries(
    companies: list[CompanyProfile],
    clusters: list[CompetitorCluster],
    lookback_days: int,
    *,
    max_company_terms: int = 4,
    max_competitors: int = 3,
    max_bucket_terms: int = 5,
) -> list[SearchQuery]:
    """Generate search queries across portfolio, competitors, and industry."""
    queries: list[SearchQuery] = []
    created_at = datetime.now(timezone.utc)
    cluster_lookup = {cluster.cluster_id: cluster for cluster in clusters}

    for company in companies:
        seeds = company.search_query_seeds or {}
        company_terms = _dedupe_terms(seeds.get("company_terms", []) + [company.name])
        deal_terms = seeds.get("deal_terms", []) or DEFAULT_DEAL_TERMS
        activity_terms = _dedupe_terms(
            seeds.get("product_terms", []) + DEFAULT_ACTIVITY_TERMS
        )

        company_group = _or_group(company_terms, max_terms=max_company_terms)
        deal_group = _or_group(deal_terms, max_terms=max_bucket_terms)
        activity_group = _or_group(activity_terms, max_terms=max_bucket_terms)

        queries.append(
            _make_query(
                query_text=_compose_query(
                    company_group,
                    deal_group,
                    company.company_context,
                    lookback_days,
                ),
                query_type=QueryType.PORTFOLIO,
                related_company=company.name,
                related_sector=company.sector,
                created_at=created_at,
            )
        )

        queries.append(
            _make_query(
                query_text=_compose_query(
                    company_group,
                    activity_group,
                    company.company_context,
                    lookback_days,
                ),
                query_type=QueryType.PORTFOLIO,
                related_company=company.name,
                related_sector=company.sector,
                created_at=created_at,
            )
        )

        gp_bullhound_query = _compose_domain_query(
            "gpbullhound.com",
            company_group,
            deal_group,
            company.company_context,
            lookback_days,
        )
        queries.append(
            _make_query(
                query_text=gp_bullhound_query,
                query_type=QueryType.GP_BULLHOUND,
                related_company=company.name,
                related_sector=company.sector,
                created_at=created_at,
            )
        )

        for competitor in _dedupe_terms(company.competitors_candidate)[:max_competitors]:
            competitor_group = _or_group([competitor], max_terms=1)
            queries.append(
                _make_query(
                    query_text=_compose_query(
                        competitor_group,
                        deal_group,
                        company.sector,
                        lookback_days,
                    ),
                    query_type=QueryType.COMPETITOR,
                    related_company=company.name,
                    related_sector=company.sector,
                    created_at=created_at,
                )
            )

        cluster = cluster_lookup.get(company.cluster_id or "")
        if cluster:
            buckets = cluster.search_keyword_buckets or {}
            industry_terms = _dedupe_terms(
                company.competitor_cluster_tags + buckets.get("product", [])
            )
            industry_group = _or_group(industry_terms, max_terms=max_bucket_terms)
            events_group = _or_group(
                buckets.get("events", []) or DEFAULT_DEAL_TERMS,
                max_terms=max_bucket_terms,
            )
            signals_terms = _dedupe_terms(
                buckets.get("commercial_signals", []) + buckets.get("leadership", [])
            )
            signals_group = _or_group(signals_terms, max_terms=max_bucket_terms)

            if industry_group and events_group:
                queries.append(
                    _make_query(
                        query_text=_compose_query(
                            industry_group,
                            events_group,
                            cluster.what_it_is or company.sector,
                            lookback_days,
                        ),
                        query_type=QueryType.INDUSTRY,
                        related_company=company.name,
                        related_sector=company.sector,
                        created_at=created_at,
                    )
                )

            if industry_group and signals_group:
                queries.append(
                    _make_query(
                        query_text=_compose_query(
                            industry_group,
                            signals_group,
                            cluster.what_it_is or company.sector,
                            lookback_days,
                        ),
                        query_type=QueryType.INDUSTRY,
                        related_company=company.name,
                        related_sector=company.sector,
                        created_at=created_at,
                    )
                )

    return queries


def build_source_queries(
    domains: list[str],
    lookback_days: int,
    *,
    max_domains: int = 10,
) -> list[SearchQuery]:
    """Build broad domain-restricted queries for trusted sources."""
    queries: list[SearchQuery] = []
    created_at = datetime.now(timezone.utc)

    focus_terms = _dedupe_terms(DEFAULT_DEAL_TERMS + DEFAULT_ACTIVITY_TERMS)
    focus_group = _or_group(focus_terms, max_terms=6)

    for domain in _dedupe_terms(domains)[:max_domains]:
        query_text = _compose_domain_query(domain, "", focus_group, None, lookback_days)
        queries.append(
            _make_query(
                query_text=query_text,
                query_type=QueryType.INDUSTRY,
                related_company=None,
                related_sector=f"source:{domain}",
                created_at=created_at,
            )
        )

    return queries


def _make_query(
    *,
    query_text: str,
    query_type: QueryType,
    related_company: str | None,
    related_sector: str | None,
    created_at: datetime,
) -> SearchQuery:
    query_id = hashlib.sha256(
        f"{query_type}:{related_company}:{query_text}".encode("utf-8")
    ).hexdigest()
    return SearchQuery(
        id=query_id,
        query_text=query_text,
        query_type=query_type,
        related_company=related_company,
        related_sector=related_sector,
        created_at=created_at,
    )


def _compose_query(
    subject_group: str,
    focus_group: str,
    context: str | None,
    lookback_days: int,
) -> str:
    """Compose a natural language search query.

    Note: lookback_days is kept for signature compatibility but recency
    is handled via API's search_recency_filter parameter.
    """
    parts = [subject_group, focus_group]
    if context:
        parts.append(context)
    return " ".join(part for part in parts if part)


def _compose_domain_query(
    domain: str,
    subject_group: str,
    focus_group: str,
    context: str | None,
    lookback_days: int,
) -> str:
    """Compose a domain-restricted search query.

    The site: prefix is parsed by PerplexityClient to set domain_filter.
    """
    parts = [f"site:{domain}", subject_group, focus_group]
    if context:
        parts.append(context)
    return " ".join(part for part in parts if part)


def _or_group(terms: Iterable[str], *, max_terms: int) -> str:
    cleaned = _dedupe_terms(terms)
    sliced = cleaned[:max_terms]
    if not sliced:
        return ""
    quoted = [_quote(term) for term in sliced if term]
    if not quoted:
        return ""
    group = " OR ".join(quoted)
    if len(quoted) > 1:
        return f"({group})"
    return group


def _quote(term: str) -> str:
    escaped = term.replace('"', "'").strip()
    if not escaped:
        return ""
    return f'"{escaped}"'


def _dedupe_terms(terms: Iterable[str]) -> list[str]:
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
