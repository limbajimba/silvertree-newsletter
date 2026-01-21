"""Data models for the newsletter workflow."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class NewsCategory(str, Enum):
    """Categories for news items."""

    MA_DEAL = "ma_deal"
    FUNDRAISING = "fundraising"
    PARTNERSHIP = "partnership"
    PRODUCT_LAUNCH = "product_launch"
    PERSONNEL_CHANGE = "personnel_change"
    STRATEGIC_UPDATE = "strategic_update"
    OTHER = "other"


class RelevanceLevel(str, Enum):
    """Relevance level for news items."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class QueryType(str, Enum):
    """Search query category."""

    PORTFOLIO = "portfolio"
    COMPETITOR = "competitor"
    INDUSTRY = "industry"
    GP_BULLHOUND = "gp_bullhound"


class SearchContextSize(str, Enum):
    """Perplexity search context size option."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class UserLocation(BaseModel):
    """User location for geo-targeted search results."""

    country: str  # ISO 3166-1 alpha-2: "US", "GB"
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class Company(BaseModel):
    """A company being tracked."""

    name: str
    description: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    is_portfolio_company: bool = False
    sector: Optional[str] = None


class NewsItem(BaseModel):
    """A news item collected from sources."""

    id: str = Field(default_factory=lambda: "")
    title: str
    summary: str
    source: str
    source_url: str
    published_date: Optional[datetime] = None
    category: NewsCategory = NewsCategory.OTHER
    related_companies: list[str] = Field(default_factory=list)
    raw_content: Optional[str] = None


class CompanyProfile(BaseModel):
    """Portfolio company context for query building."""

    company_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    company_context: Optional[str] = None
    websites: list[str] = Field(default_factory=list)
    sector: Optional[str] = None
    cluster_id: Optional[str] = None
    # New structure for direct vs indirect competitors
    direct_competitors: list[str] = Field(default_factory=list)
    indirect_competitors: list[str] = Field(default_factory=list)
    # Legacy field - kept for backwards compatibility
    competitors_candidate: list[str] = Field(default_factory=list)
    competitor_cluster_tags: list[str] = Field(default_factory=list)
    search_query_seeds: dict[str, list[str]] = Field(default_factory=dict)
    ownership_note: Optional[str] = None  # For flagging ownership questions


class CompetitorCluster(BaseModel):
    """Industry cluster context for query building."""

    cluster_id: str
    name: str
    what_it_is: Optional[str] = None
    search_keyword_buckets: dict[str, list[str]] = Field(default_factory=dict)
    canonical_competitors_seed: list[str] = Field(default_factory=list)


class SearchQuery(BaseModel):
    """A single search query tied to a portfolio company."""

    id: str
    query_text: str
    query_type: QueryType
    related_company: Optional[str] = None
    related_cluster: Optional[str] = None
    related_sector: Optional[str] = None
    domain_filter: Optional[list[str]] = None  # e.g., ["gpbullhound.com"]
    domain_denylist: Optional[list[str]] = None  # e.g., ["reddit.com", "quora.com"]
    recency_filter: str = "week"  # week, month, day
    search_after_date: Optional[str] = None  # format MM/DD/YYYY
    search_before_date: Optional[str] = None  # format MM/DD/YYYY
    last_updated_after: Optional[str] = None  # format MM/DD/YYYY
    last_updated_before: Optional[str] = None  # format MM/DD/YYYY
    user_location: Optional[UserLocation] = None
    search_context_size: SearchContextSize = SearchContextSize.MEDIUM
    original_query_text: Optional[str] = None  # stores pre-optimization text
    was_optimized: bool = False
    created_at: datetime


class SearchSource(str, Enum):
    """Which API/source returned the result."""

    PERPLEXITY = "perplexity"
    TAVILY = "tavily"
    RSS = "rss"


class SearchResult(BaseModel):
    """A single result from a search query."""

    url: str
    title: str
    snippet: str
    source_name: Optional[str] = None  # e.g., "TechCrunch", "GP Bullhound"
    published_date: Optional[datetime] = None
    query_id: str  # Links back to SearchQuery
    search_source: SearchSource = SearchSource.PERPLEXITY


class SearchResponse(BaseModel):
    """Response from a search API containing multiple results."""

    query: SearchQuery
    results: list[SearchResult] = Field(default_factory=list)
    raw_response: Optional[str] = None  # For debugging
    success: bool = True
    error_message: Optional[str] = None
    executed_at: datetime


class AnalyzedNewsItem(BaseModel):
    """A news item with analysis added."""

    news_item: NewsItem
    relevance_level: RelevanceLevel
    relevance_explanation: str
    impact_on_portfolio: Optional[str] = None
    related_portfolio_companies: list[str] = Field(default_factory=list)
    related_competitors: list[str] = Field(default_factory=list)


class CarveoutOpportunity(BaseModel):
    """A potential carve-out opportunity identified from a deal."""

    deal_news_item: NewsItem
    target_company: str
    potential_unit: str
    rationale: str
    estimated_relevance: RelevanceLevel
    next_steps: Optional[str] = None


class NewsletterSection(BaseModel):
    """A section of the newsletter."""

    title: str
    items: list[AnalyzedNewsItem] = Field(default_factory=list)
    summary: Optional[str] = None


class Newsletter(BaseModel):
    """The complete newsletter."""

    subject: str
    generated_date: datetime
    period_start: datetime
    period_end: datetime
    portfolio_section: NewsletterSection
    competitor_section: NewsletterSection
    major_deals_section: NewsletterSection
    carveout_section: Optional[NewsletterSection] = None
    executive_summary: str
