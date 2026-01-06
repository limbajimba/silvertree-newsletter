"""LangGraph workflow definition for the newsletter pipeline.

Pipeline:
    Initialize → Collect (RSS + Search) → Triage → Dedupe → Fetch Full Content → Analyze → Curate → Compose → Save → Send

Uses LangGraph for:
- State management between nodes
- Parallel collection (RSS + Search)
- Conditional routing (skip analysis if no relevant items)
"""

from __future__ import annotations

import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from silvertree_newsletter.workflow.state import NewsletterState
from silvertree_newsletter.workflow.nodes import (
    initialize_node,
    collect_rss_node,
    collect_search_node,
    dedupe_node,
    triage_node,
    fetch_full_content_node,
    analyze_node,
    curate_node,
    compose_node,
    save_output_node,
    send_email_node,
)

logger = logging.getLogger(__name__)


def should_analyze(state: NewsletterState) -> Literal["analyze", "skip_to_compose"]:
    """Determine if we should run analysis or skip."""
    relevant_count = len(state.get("relevant_items", []))
    if relevant_count == 0:
        logger.info("No relevant items - skipping analysis")
        return "skip_to_compose"
    return "analyze"


def create_newsletter_graph() -> StateGraph:
    """Create the newsletter workflow graph.

    Flow:
        START
          ↓
        initialize
          ↓
        collect_rss → (parallel) → collect_search
          ↓                           ↓
          └─────────┬─────────────────┘
                    ↓
                  triage
                    ↓
                  dedupe
                    ↓
           ┌───────┴───────┐
           ↓               ↓
        fetch_full_content  skip_to_compose
           ↓                       │
         analyze                   │
           ↓                       │
         curate                    │
           ↓                       │
        compose ←──────────────────┘
          ↓
         save
          ↓
       send_email
          ↓
         END
    """
    # Create the graph
    graph = StateGraph(NewsletterState)

    # Add nodes
    graph.add_node("initialize", initialize_node)
    graph.add_node("collect_rss", collect_rss_node)
    graph.add_node("collect_search", collect_search_node)
    graph.add_node("dedupe", dedupe_node)
    graph.add_node("triage", triage_node)
    graph.add_node("fetch_full_content", fetch_full_content_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("curate", curate_node)
    graph.add_node("compose", compose_node)
    graph.add_node("save", save_output_node)
    graph.add_node("send_email", send_email_node)

    # Define edges
    graph.set_entry_point("initialize")

    # After initialize, run both collectors in parallel
    graph.add_edge("initialize", "collect_rss")
    graph.add_edge("initialize", "collect_search")
    graph.add_edge("collect_rss", "triage")
    graph.add_edge("collect_search", "triage")
    graph.add_edge("triage", "dedupe")

    # Conditional: analyze only if we have relevant items
    graph.add_conditional_edges(
        "dedupe",
        should_analyze,
        {
            "analyze": "fetch_full_content",
            "skip_to_compose": "compose",
        }
    )

    graph.add_edge("fetch_full_content", "analyze")
    graph.add_edge("analyze", "curate")
    graph.add_edge("curate", "compose")
    graph.add_edge("compose", "save")
    graph.add_edge("save", "send_email")
    graph.add_edge("send_email", END)

    return graph


def compile_newsletter_workflow():
    """Compile the newsletter workflow for execution."""
    graph = create_newsletter_graph()
    return graph.compile()


# Convenience function to run the workflow
async def run_newsletter_workflow() -> NewsletterState:
    """Run the complete newsletter workflow."""
    logger.info("Starting newsletter workflow...")

    workflow = compile_newsletter_workflow()

    # Initial state (empty - initialize node will populate)
    initial_state: NewsletterState = {
        "portfolio_context": "",
        "lookback_days": 7,
        "raw_items": [],
        "deduped_items": [],
        "collection_errors": [],
        "dedupe_stats": {},
        "relevance_thresholds": {},
        "triaged_items": [],
        "relevant_items": [],
        "triage_stats": {},
        "analyzed_items": [],
        "carve_out_opportunities": [],
        "newsletter": None,
        "newsletter_html": "",
        "started_at": None,
        "completed_at": None,
        "errors": [],
        "metrics": {},
    }

    # Run the workflow
    final_state = await workflow.ainvoke(initial_state)

    logger.info("Newsletter workflow complete!")
    logger.info(f"Metrics: {final_state.get('metrics', {})}")

    return final_state
