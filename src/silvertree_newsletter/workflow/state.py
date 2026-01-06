"""LangGraph state definitions for the newsletter workflow.

This defines the data that flows through the pipeline:
Collection → Triage → Dedupe → Fetch Full Content → Analysis → Curate → Compose → Save
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, TypedDict
import operator

from pydantic import BaseModel, Field


# =============================================================================
# ENUMS
# =============================================================================

class ItemCategory(str, Enum):
    """Category assigned by triage agent."""
    PORTFOLIO = "portfolio"           # Direct news about portfolio company
    COMPETITOR = "competitor"         # News about a competitor
    MAJOR_DEAL = "major_deal"         # M&A, fundraising, large partnership
    INDUSTRY = "industry"             # Broader industry news
    NOT_RELEVANT = "not_relevant"     # Filter out


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
    """Carve-out opportunity assessment."""
    HIGH = "high"           # Clear non-core unit, strategic fit
    MEDIUM = "medium"       # Possible opportunity, needs more analysis
    LOW = "low"             # Unlikely but worth noting
    NONE = "none"           # No carve-out potential
    NOT_APPLICABLE = "n/a"  # Not an M&A deal


class RelevanceLevel(str, Enum):
    """How relevant to SilverTree."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# =============================================================================
# DATA MODELS - Pipeline Stages
# =============================================================================

class RawNewsItem(BaseModel):
    """Raw news item from collection stage."""
    id: str
    title: str
    summary: str
    source: str                    # e.g., "finextra", "techcrunch"
    source_url: str
    published_date: datetime | None = None
    full_text: str | None = None
    full_text_source: str | None = None


class TriagedItem(BaseModel):
    """News item after triage agent processing."""
    # Original item
    raw_item: RawNewsItem

    # Triage results
    is_relevant: bool
    category: ItemCategory
    deal_type: DealType
    relevance_level: RelevanceLevel
    confidence: int = Field(ge=0, le=100)  # 0-100

    # Entity linking
    related_portfolio_company: str | None = None
    related_competitors: list[str] = Field(default_factory=list)
    related_sector: str | None = None

    # Brief reason (1 sentence)
    triage_reason: str


class AnalyzedItem(BaseModel):
    """News item after deep analysis agent processing."""
    # From triage
    triaged_item: TriagedItem

    # Deep analysis results
    why_it_matters: str              # 2-3 sentences for newsletter
    strategic_implications: str      # Detailed analysis
    impact_on_silvertree: str = ""

    # For competitor items
    competitive_threat_level: str | None = None  # "high", "medium", "low"
    affected_portfolio_companies: list[str] = Field(default_factory=list)

    # For deals - carve-out analysis
    carve_out_potential: CarveOutPotential = CarveOutPotential.NOT_APPLICABLE
    carve_out_rationale: str | None = None
    carve_out_target_units: list[str] = Field(default_factory=list)

    # Key entities extracted
    key_entities: dict[str, str] = Field(default_factory=dict)  # {name: role}

    # Signal quality
    signal_score: int = Field(default=50, ge=0, le=100)
    evidence: list[str] = Field(default_factory=list)


class CarveOutOpportunity(BaseModel):
    """Flagged carve-out opportunity for newsletter highlight."""
    source_item: AnalyzedItem
    source_items: list[AnalyzedItem] = Field(default_factory=list)
    target_company: str
    potential_units: list[str]
    strategic_fit_rationale: str
    recommended_action: str
    priority: str  # "high", "medium"


# =============================================================================
# NEWSLETTER OUTPUT MODELS
# =============================================================================

class SourceLink(BaseModel):
    """Source link for a newsletter item."""
    title: str
    url: str
    source: str | None = None


class NewsletterItem(BaseModel):
    """Composed newsletter item (possibly merged)."""
    headline: str
    summary: str
    impact_on_silvertree: str
    category: ItemCategory
    deal_type: DealType
    portfolio_company: str | None = None
    cluster: str | None = None
    signal_score: int = Field(default=50, ge=0, le=100)
    primary_date: datetime | None = None
    sources: list[SourceLink] = Field(default_factory=list)
    source_item_ids: list[str] = Field(default_factory=list)


class NewsletterGroup(BaseModel):
    """Grouped items within a section."""
    name: str
    items: list[NewsletterItem] = Field(default_factory=list)


class NewsletterSection(BaseModel):
    """A section of the newsletter."""
    title: str
    items: list[NewsletterItem] = Field(default_factory=list)
    groups: list[NewsletterGroup] = Field(default_factory=list)
    section_summary: str | None = None


class Newsletter(BaseModel):
    """Complete newsletter ready for email."""
    subject: str
    generated_date: datetime
    period_start: datetime
    period_end: datetime

    executive_summary: str

    portfolio_section: NewsletterSection
    deals_section: NewsletterSection
    competitive_cluster_section: NewsletterSection
    carve_out_section: NewsletterSection | None = None

    total_items_processed: int
    total_relevant_items: int


# =============================================================================
# LANGGRAPH STATE
# =============================================================================

class NewsletterState(TypedDict):
    """Main state that flows through the LangGraph workflow.

    Each stage reads from and writes to this state.
    """
    # === INPUT ===
    portfolio_context: str           # Company/competitor info for prompts
    lookback_days: int               # How far back to search

    # === COLLECTION STAGE ===
    raw_items: Annotated[list[RawNewsItem], operator.add]  # Accumulates from multiple sources
    deduped_items: list[RawNewsItem]
    collection_errors: Annotated[list[str], operator.add]
    dedupe_stats: dict
    relevance_thresholds: dict

    # === TRIAGE STAGE ===
    triaged_items: list[TriagedItem]
    relevant_items: list[TriagedItem]  # Filtered (is_relevant=True)
    triage_stats: dict                  # {"total": N, "relevant": N, "by_category": {...}}

    # === ANALYSIS STAGE ===
    analyzed_items: list[AnalyzedItem]
    carve_out_opportunities: list[CarveOutOpportunity]

    # === COMPOSE STAGE ===
    newsletter: Newsletter | None
    newsletter_html: str

    # === METADATA ===
    started_at: datetime
    completed_at: datetime | None
    errors: list[str]
    metrics: Annotated[dict, operator.or_]
