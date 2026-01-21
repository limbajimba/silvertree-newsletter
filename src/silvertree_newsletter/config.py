"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # LLM Configuration
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    default_llm_provider: str = "gemini"  # "openai", "anthropic", or "gemini"
    default_model: str = "gemini-2.5-flash"
    triage_model: str = ""
    analysis_model: str = ""
    composer_model: str = ""
    dedupe_model: str = ""
    carve_out_research_model: str = ""

    # Email Configuration
    from_email: str = "newsletter@silvertree-equity.com"
    to_email: str = "romil@silvertree-equity.com"
    send_email: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: float = 30.0

    # Scheduling
    newsletter_day: str = "monday"  # Day of week to send newsletter
    newsletter_hour: int = 8  # Hour to send (24h format)

    # Data Sources
    gp_bullhound_rss: str = "https://www.gpbullhound.com/feed/"
    csv_path: str = "silvertree_tracking_scope.csv"
    company_data_path: str = "config/silvertree_companies_competitors.json"
    prompt_context_path: str = "config/prompt_context.json"
    sources_catalog_path: str = "config/sources_catalog.json"
    output_dir: str = "data/news_results"

    # Test/throughput caps
    rss_max_items_per_feed: int = 30
    max_search_companies: int = 0
    max_queries_per_type: int = 0
    max_search_queries_total: int = 0

    # Perplexity Search
    perplexity_api_key: str = ""
    perplexity_model: str = "sonar"
    perplexity_max_items: int = 8
    perplexity_rpm: int = 50  # Tier 0/1 limit for sonar model
    perplexity_max_retries: int = 3
    perplexity_max_concurrent: int = 10  # Max parallel searches (rate limit still applies)
    search_lookback_days: int = 7
    keep_undated_items: bool = False
    max_article_age_days: int = 7  # Hard cutoff - reject anything older
    request_timeout_seconds: float = 30.0
    # Perplexity API enhancements
    perplexity_search_context_size: str = "medium"  # low, medium, high
    perplexity_default_location_country: str = "GB"  # UK focus for SilverTree
    perplexity_use_date_filters: bool = True  # Use search_after_date filters
    perplexity_domain_denylist: str = "reddit.com,quora.com"  # Exclude low-quality sources
    dedupe_similarity_threshold: float = 0.9
    min_signal_score: int = 55
    max_portfolio_items: int = 8
    max_competitor_items: int = 10
    max_deal_items: int = 12
    max_industry_items: int = 10
    max_items_per_portfolio_company: int = 3
    max_items_per_cluster: int = 5

    # Full-text enrichment
    full_text_timeout_seconds: float = 20.0
    full_text_requests_per_minute: int = 60
    full_text_max_concurrency: int = 6
    full_text_max_chars: int = 4000
    full_text_min_chars: int = 200
    max_full_text_items: int = 60
    max_domain_source_queries: int = 12
    carve_out_research_enabled: bool = True
    carve_out_research_max_sources: int = 4

    # Deep Research (Google Gemini Interactions API)
    carve_out_deep_research_enabled: bool = True
    deep_research_poll_interval: int = 30  # seconds
    deep_research_max_wait_minutes: int = 45
    deep_research_high_priority_only: bool = True  # Only run deep research for high-priority carve-outs
    portfolio_context_dir: str = "config/portfolio_context"

    # LLM throughput
    llm_requests_per_minute: int = 60
    triage_max_workers: int = 4
    analysis_max_workers: int = 3

    # Application
    debug: bool = False
    log_level: str = "INFO"


settings = Settings()
