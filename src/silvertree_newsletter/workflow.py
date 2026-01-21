"""Legacy LangGraph workflow for portfolio news aggregation.

Deprecated: use `silvertree_newsletter.workflow.graph` for the full multi-agent pipeline.
"""

from __future__ import annotations

import json
import operator
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from silvertree_newsletter.config import settings
from silvertree_newsletter.models.schemas import (
    CompanyProfile,
    CompetitorCluster,
    NewsItem,
    SearchQuery,
)
from silvertree_newsletter.services.perplexity import PerplexityClient
from silvertree_newsletter.tools.company_context_loader import load_company_context
from silvertree_newsletter.tools.query_builder import build_search_queries


class WorkflowState(TypedDict):
    """State that flows through the workflow."""

    company_profiles: list[CompanyProfile]
    competitor_clusters: list[CompetitorCluster]
    queries: list[SearchQuery]
    news_items: Annotated[list[NewsItem], operator.add]
    errors: Annotated[list[str], operator.add]
    output_path: str


def _recency_filter(days: int) -> str | None:
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    if days <= 31:
        return "month"
    return "year"


async def load_company_profiles(state: WorkflowState) -> WorkflowState:
    """Load portfolio company context from JSON."""
    companies, clusters = load_company_context(settings.company_data_path)
    return {
        "company_profiles": companies,
        "competitor_clusters": clusters,
    }


async def build_queries(state: WorkflowState) -> WorkflowState:
    """Build portfolio, competitor, and industry queries."""
    queries = build_search_queries(
        state.get("company_profiles", []),
        state.get("competitor_clusters", []),
        settings.search_lookback_days,
    )
    return {"queries": queries}


def route_to_searches(state: WorkflowState) -> list[Send]:
    """Fan-out to Perplexity search for each query."""
    return [
        Send("search_perplexity", {"query": query})
        for query in state.get("queries", [])
    ]


async def search_perplexity(state: dict) -> dict:
    """Run a Perplexity search for a single query."""
    query = state["query"]

    if not settings.perplexity_api_key:
        return {
            "news_items": [],
            "errors": ["Missing PERPLEXITY_API_KEY"],
        }

    client = PerplexityClient(
        api_key=settings.perplexity_api_key,
        model=settings.perplexity_model,
        timeout_seconds=settings.request_timeout_seconds,
        max_items=settings.perplexity_max_items,
        recency_filter=_recency_filter(settings.search_lookback_days),
        lookback_days=settings.search_lookback_days,
        keep_undated=settings.keep_undated_items,
        max_age_days=settings.max_article_age_days,
    )

    try:
        items = await client.search(query)
    except Exception as exc:  # pragma: no cover - defensive logging
        company_name = query.related_company or "unknown"
        return {
            "news_items": [],
            "errors": [f"Perplexity search failed for {company_name}: {exc}"],
        }

    return {"news_items": items, "errors": []}


async def save_results(state: WorkflowState) -> WorkflowState:
    """Persist aggregated results to a JSON file."""
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_path = output_dir / f"news_{timestamp}.json"

    items = [item.model_dump(mode="json") for item in state.get("news_items", [])]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": items,
        "errors": state.get("errors", []),
    }
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return {"output_path": str(output_path)}


def create_newsletter_workflow() -> StateGraph:
    """Create and return the newsletter aggregation workflow."""
    workflow = StateGraph(WorkflowState)

    workflow.add_node("load_company_profiles", load_company_profiles)
    workflow.add_node("build_queries", build_queries)
    workflow.add_node("search_perplexity", search_perplexity)
    workflow.add_node("save_results", save_results)

    workflow.set_entry_point("load_company_profiles")
    workflow.add_edge("load_company_profiles", "build_queries")
    workflow.add_conditional_edges(
        "build_queries",
        route_to_searches,
        ["search_perplexity"],
    )
    workflow.add_edge("search_perplexity", "save_results")
    workflow.add_edge("save_results", END)

    return workflow.compile()
