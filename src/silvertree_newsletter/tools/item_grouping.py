"""Helpers for grouping items by portfolio company and competitive cluster."""

from __future__ import annotations

from typing import Iterable

from silvertree_newsletter.models.schemas import CompanyProfile, CompetitorCluster
from silvertree_newsletter.workflow.state import TriagedItem, AnalyzedItem


def build_company_lookups(
    companies: Iterable[CompanyProfile],
    clusters: Iterable[CompetitorCluster],
) -> tuple[dict[str, CompanyProfile], dict[str, CompetitorCluster]]:
    company_lookup = {company.name.lower(): company for company in companies if company.name}
    cluster_lookup = {cluster.cluster_id: cluster for cluster in clusters if cluster.cluster_id}
    return company_lookup, cluster_lookup


def resolve_portfolio_company(
    item: TriagedItem | AnalyzedItem,
    company_lookup: dict[str, CompanyProfile],
) -> str | None:
    triaged = item.triaged_item if isinstance(item, AnalyzedItem) else item
    if triaged.related_portfolio_company:
        return triaged.related_portfolio_company

    text = f"{triaged.raw_item.title} {triaged.raw_item.summary}".lower()
    for name, company in company_lookup.items():
        if name in text:
            return company.name
    return None


def resolve_cluster(
    item: TriagedItem | AnalyzedItem,
    company_lookup: dict[str, CompanyProfile],
    cluster_lookup: dict[str, CompetitorCluster],
) -> str | None:
    triaged = item.triaged_item if isinstance(item, AnalyzedItem) else item
    portfolio_company = resolve_portfolio_company(item, company_lookup)
    if portfolio_company:
        company = company_lookup.get(portfolio_company.lower())
        if company and company.cluster_id:
            cluster = cluster_lookup.get(company.cluster_id)
            if cluster:
                return cluster.name

    if triaged.related_sector:
        sector = triaged.related_sector.lower()
        for cluster in cluster_lookup.values():
            if sector in (cluster.name or "").lower():
                return cluster.name
            if cluster.what_it_is and sector in cluster.what_it_is.lower():
                return cluster.name

    return None
