"""LangGraph workflow definition for the newsletter pipeline.

Pipeline:
    Initialize → Collect (RSS + Search) → Triage → Dedupe → Fetch Full Content → Analyze → Curate → Carve-Out Research → Compose → Save → Send

Uses LangGraph for:
- State management between nodes
- Parallel collection (RSS + Search)
- Conditional routing (skip analysis if no relevant items)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

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
    carve_out_research_node,
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
     carve_out_research            │
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
    graph.add_node("carve_out_research", carve_out_research_node)
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
    graph.add_edge("curate", "carve_out_research")
    graph.add_edge("carve_out_research", "compose")
    graph.add_edge("compose", "save")
    graph.add_edge("save", "send_email")
    graph.add_edge("send_email", END)

    return graph


def compile_newsletter_workflow(checkpointer=None):
    """Compile the newsletter workflow for execution.

    Args:
        checkpointer: Optional checkpointer for state persistence (e.g., AsyncSqliteSaver)
    """
    graph = create_newsletter_graph()
    return graph.compile(checkpointer=checkpointer)


# Convenience function to run the workflow
async def run_newsletter_workflow(thread_id: str = "default", resume: bool = False) -> NewsletterState:
    """Run the complete newsletter workflow with optional checkpointing.

    Args:
        thread_id: Unique identifier for this workflow run (for checkpointing)
        resume: If True, resume from last checkpoint; if False, start fresh
    """
    logger.info("Starting newsletter workflow...", extra={"thread_id": thread_id, "resume": resume})

    # Set up SQLite checkpointing for state persistence
    checkpoint_dir = Path("data/checkpoints")
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_db = checkpoint_dir / "workflow.sqlite"

    # Initial state definition (used for fresh starts or when no checkpoint exists)
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
        "carve_out_research_report": None,
        "carve_out_research_path": None,
        "newsletter": None,
        "newsletter_html": "",
        "started_at": None,
        "completed_at": None,
        "errors": [],
        "metrics": {},
    }

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_db)) as checkpointer:
        workflow = compile_newsletter_workflow(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": thread_id}}

        if resume:
            # Check if a checkpoint exists for this thread_id
            checkpoint = await checkpointer.aget(config)
            if checkpoint is None:
                logger.warning(f"No checkpoint found for thread_id '{thread_id}'. Starting fresh instead.")
                final_state = await workflow.ainvoke(initial_state, config)
            else:
                # Resume from last checkpoint
                logger.info("Resuming from last checkpoint...")
                final_state = await workflow.ainvoke(None, config)
        else:
            # Start fresh
            logger.info("Starting new workflow (checkpoints will be saved)...")
            final_state = await workflow.ainvoke(initial_state, config)

    logger.info("Newsletter workflow complete!")
    logger.info(f"Metrics: {final_state.get('metrics', {})}")

    return final_state
