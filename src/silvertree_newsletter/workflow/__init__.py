"""Newsletter workflow using LangGraph."""

from silvertree_newsletter.workflow.state import (
    NewsletterState,
    RawNewsItem,
    TriagedItem,
    AnalyzedItem,
    CarveOutOpportunity,
    Newsletter,
    ItemCategory,
    DealType,
    CarveOutPotential,
    RelevanceLevel,
)
from silvertree_newsletter.workflow.graph import (
    create_newsletter_graph,
    compile_newsletter_workflow,
    run_newsletter_workflow,
)

__all__ = [
    # State
    "NewsletterState",
    "RawNewsItem",
    "TriagedItem",
    "AnalyzedItem",
    "CarveOutOpportunity",
    "Newsletter",
    # Enums
    "ItemCategory",
    "DealType",
    "CarveOutPotential",
    "RelevanceLevel",
    # Graph
    "create_newsletter_graph",
    "compile_newsletter_workflow",
    "run_newsletter_workflow",
]
