"""LangGraph node functions for the newsletter workflow.

Each node function:
- Takes the current state
- Performs its operation
- Returns updated state fields
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from silvertree_newsletter.config import settings
from silvertree_newsletter.services.rss_collector import RSSCollector
from silvertree_newsletter.services.perplexity import PerplexityClient
from silvertree_newsletter.services.content_fetcher import ContentFetcher
from silvertree_newsletter.services.email_sender import SmtpEmailSender
from silvertree_newsletter.agents.triage_agent import TriageAgent
from silvertree_newsletter.agents.analysis_agent import AnalysisAgent
from silvertree_newsletter.agents.email_composer import EmailComposerAgent
from silvertree_newsletter.agents.dedupe_agent import DedupeAgent
from silvertree_newsletter.workflow.state import (
    NewsletterState,
    RawNewsItem,
    TriagedItem,
    ItemCategory,
    CarveOutPotential,
)
from silvertree_newsletter.tools.company_context_loader import load_company_context
from silvertree_newsletter.tools.query_builder import build_search_queries, build_source_queries
from silvertree_newsletter.tools.prompt_context_loader import (
    load_prompt_context,
    build_prompt_context_summary,
    build_item_context_for_triage,
    build_item_context_for_analysis,
    extract_relevance_thresholds,
)
from silvertree_newsletter.tools.source_catalog import load_source_catalog
from silvertree_newsletter.tools.item_grouping import build_company_lookups, resolve_portfolio_company, resolve_cluster

logger = logging.getLogger(__name__)

def _recency_filter(days: int) -> str | None:
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    if days <= 31:
        return "month"
    return "year"


def _limit_queries_by_type(queries: list, limit: int) -> list:
    if limit <= 0:
        return queries
    limited = []
    counts: dict[str, int] = {}
    for query in queries:
        key = query.query_type.value
        if counts.get(key, 0) >= limit:
            continue
        counts[key] = counts.get(key, 0) + 1
        limited.append(query)
    if len(limited) < len(queries):
        logger.info(f"Limiting queries per type to {limit}: {len(limited)}/{len(queries)} kept")
    return limited


def _split_emails(value: str) -> list[str]:
    if not value:
        return []
    cleaned = value.replace(";", ",")
    return [email.strip() for email in cleaned.split(",") if email.strip()]


# =============================================================================
# NODE: INITIALIZE
# =============================================================================

def initialize_node(state: NewsletterState) -> dict:
    """Initialize the workflow with portfolio context."""
    logger.info("Initializing workflow...")

    # Load portfolio context
    json_path = Path(settings.company_data_path)
    if not json_path.exists():
        json_path = Path(__file__).parent.parent.parent.parent / settings.company_data_path

    companies, clusters = load_company_context(json_path)

    # Build portfolio context string for prompts
    lines = ["SilverTree Equity Portfolio Companies:"]
    for company in companies:
        lines.append(f"\n• {company.name}")
        if company.company_context:
            lines.append(f"  {company.company_context}")
        if company.sector:
            lines.append(f"  Sector: {company.sector}")
        if company.competitors_candidate:
            lines.append(f"  Competitors: {', '.join(company.competitors_candidate[:5])}")

    if clusters:
        lines.append("\n\nCompetitor Clusters to Monitor:")
        for cluster in clusters:
            lines.append(f"\n• {cluster.name}")
            if cluster.what_it_is:
                lines.append(f"  {cluster.what_it_is}")
            if cluster.canonical_competitors_seed:
                lines.append(f"  Key players: {', '.join(cluster.canonical_competitors_seed[:5])}")

    prompt_context_path = Path(settings.prompt_context_path)
    if not prompt_context_path.exists():
        prompt_context_path = Path(__file__).parent.parent.parent.parent / settings.prompt_context_path

    prompt_context = load_prompt_context(prompt_context_path)
    relevance_thresholds = {}
    if prompt_context:
        summary = build_prompt_context_summary(prompt_context, companies)
        if summary:
            lines.append("\n\nLLM Guidance:")
            lines.append(summary)
        relevance_thresholds = extract_relevance_thresholds(prompt_context)

    lines.append("\n\nKey Sectors: CPG/TPM, Higher Ed SIS, Enterprise Architecture, Marketing Automation, KYC/CLM, Utilities")
    portfolio_context = "\n".join(lines)

    return {
        "portfolio_context": portfolio_context,
        "lookback_days": settings.search_lookback_days,
        "started_at": datetime.now(timezone.utc),
        "raw_items": [],
        "deduped_items": [],
        "collection_errors": [],
        "dedupe_stats": {},
        "relevance_thresholds": relevance_thresholds,
        "errors": [],
        "metrics": {},
    }


# =============================================================================
# NODE: COLLECT RSS
# =============================================================================

async def collect_rss_node(state: NewsletterState) -> dict:
    """Collect news from RSS feeds."""
    logger.info("Collecting from RSS feeds...")

    collector = RSSCollector(
        timeout_seconds=30.0,
        lookback_days=state["lookback_days"],
        max_items_per_feed=settings.rss_max_items_per_feed,
    )

    items: list[RawNewsItem] = []
    errors: list[str] = []
    feeds = None

    catalog_path = Path(settings.sources_catalog_path)
    if not catalog_path.exists():
        catalog_path = Path(__file__).parent.parent.parent.parent / settings.sources_catalog_path
    catalog = load_source_catalog(catalog_path)
    if catalog.rss_feeds:
        feeds = catalog.rss_feeds
        logger.info(f"Using {len(feeds)} RSS feeds from source catalog")

    try:
        results = await collector.collect_all(feeds)
        for feed_name, feed_items in results.items():
            for item in feed_items:
                items.append(RawNewsItem(
                    id=item.id,
                    title=item.title,
                    summary=item.summary,
                    source=item.source,
                    source_url=item.source_url,
                    published_date=item.published_date,
                ))
            logger.info(f"Collected {len(feed_items)} items from {feed_name}")
    except Exception as e:
        logger.error(f"RSS collection error: {e}")
        errors.append(f"RSS collection failed: {str(e)}")

    return {
        "raw_items": items,
        "collection_errors": errors,
        "metrics": {
            **state.get("metrics", {}),
            "rss_items": len(items),
            "rss_feeds": len(results) if "results" in locals() else 0,
        },
    }


# =============================================================================
# NODE: COLLECT SEARCH
# =============================================================================

async def collect_search_node(state: NewsletterState) -> dict:
    """Collect news via Perplexity search."""
    logger.info("Collecting via Perplexity search...")

    # Load company data for queries
    json_path = Path(settings.company_data_path)
    if not json_path.exists():
        json_path = Path(__file__).parent.parent.parent.parent / settings.company_data_path

    companies, clusters = load_company_context(json_path)
    if settings.max_search_companies and len(companies) > settings.max_search_companies:
        companies = companies[: settings.max_search_companies]
        logger.info(f"Limiting search companies to {len(companies)}")

    # Build search queries
    queries = build_search_queries(
        companies=companies,
        clusters=clusters,
        lookback_days=state["lookback_days"],
        max_company_terms=3,
        max_competitors=2,
        max_bucket_terms=4,
    )

    catalog_path = Path(settings.sources_catalog_path)
    if not catalog_path.exists():
        catalog_path = Path(__file__).parent.parent.parent.parent / settings.sources_catalog_path
    catalog = load_source_catalog(catalog_path)
    domain_sources = catalog.trusted_domains or catalog.domain_sources
    source_queries: list = []
    if domain_sources and settings.max_domain_source_queries:
        source_queries = build_source_queries(
            domains=domain_sources,
            lookback_days=state["lookback_days"],
            max_domains=settings.max_domain_source_queries,
        )

    if settings.max_queries_per_type:
        queries = _limit_queries_by_type(queries, settings.max_queries_per_type)

    if source_queries:
        queries.extend(source_queries)
        logger.info(f"Added {len(source_queries)} source-domain queries")

    if settings.max_search_queries_total and len(queries) > settings.max_search_queries_total:
        queries = queries[: settings.max_search_queries_total]
        logger.info(f"Limiting total search queries to {len(queries)}")

    by_type: dict[str, int] = {}
    for query in queries:
        by_type[query.query_type.value] = by_type.get(query.query_type.value, 0) + 1
    logger.info(f"Running {len(queries)} search queries")
    logger.info(f"Search query breakdown: {by_type}")

    client = PerplexityClient(
        api_key=settings.perplexity_api_key,
        model=settings.perplexity_model,
        timeout_seconds=settings.request_timeout_seconds,
        max_items=settings.perplexity_max_items,
        recency_filter=_recency_filter(state["lookback_days"]),
        lookback_days=state["lookback_days"],
        keep_undated=settings.keep_undated_items,
        requests_per_minute=settings.perplexity_rpm,
        max_retries=settings.perplexity_max_retries,
    )

    items: list[RawNewsItem] = []
    errors: list[str] = []

    results = await client.search_batch(queries)
    for query, query_items, error in results:
        if error:
            errors.append(f"Perplexity search failed for {query.id}: {error}")
        for item in query_items:
            source_name = item.source or urlparse(item.source_url).netloc or "perplexity"
            items.append(RawNewsItem(
                id=item.id,
                title=item.title,
                summary=item.summary,
                source=source_name,
                source_url=item.source_url,
                published_date=item.published_date,
            ))

    logger.info(f"Collected {len(items)} items from search")
    if errors:
        logger.warning(f"Perplexity search errors: {len(errors)}")

    return {
        "raw_items": items,
        "collection_errors": errors,
        "metrics": {
            **state.get("metrics", {}),
            "search_items": len(items),
            "search_queries": len(queries),
            "search_errors": len(errors),
        },
    }


# =============================================================================
# NODE: TRIAGE
# =============================================================================

def triage_node(state: NewsletterState) -> dict:
    """Triage all collected items."""
    items = state.get("raw_items", [])
    logger.info(f"Triaging {len(items)} items...")

    prompt_context = None
    companies = []
    prompt_context_path = Path(settings.prompt_context_path)
    if not prompt_context_path.exists():
        prompt_context_path = Path(__file__).parent.parent.parent.parent / settings.prompt_context_path
    prompt_context = load_prompt_context(prompt_context_path)

    json_path = Path(settings.company_data_path)
    if not json_path.exists():
        json_path = Path(__file__).parent.parent.parent.parent / settings.company_data_path
    companies, _ = load_company_context(json_path)

    agent = TriageAgent(
        api_key=settings.gemini_api_key,
        model=settings.triage_model or settings.default_model,
        portfolio_context=state["portfolio_context"],
        requests_per_minute=settings.llm_requests_per_minute,
        max_workers=settings.triage_max_workers,
    )
    logger.info(
        f"Triage agent configured (model={agent.model}, workers={agent.max_workers}, rpm={agent.requests_per_minute})"
    )

    def progress(completed: int, total: int) -> None:
        if completed % 10 == 0:
            logger.info(f"Triage progress: {completed}/{total}")

    def build_context(item: RawNewsItem) -> str | None:
        if not prompt_context:
            return None
        return build_item_context_for_triage(
            title=item.title,
            summary=item.summary,
            prompt_context=prompt_context,
            companies=companies,
        )

    triaged_items = agent.triage_batch(
        items,
        on_progress=progress,
        context_builder=build_context,
    )

    # Filter to relevant items
    relevant_items = [t for t in triaged_items if t.is_relevant]

    # Calculate stats
    by_category = {}
    for item in triaged_items:
        cat = item.category.value
        by_category[cat] = by_category.get(cat, 0) + 1

    triage_stats = {
        "total": len(triaged_items),
        "relevant": len(relevant_items),
        "by_category": by_category,
    }

    logger.info(f"Triage complete: {len(relevant_items)}/{len(triaged_items)} relevant")
    logger.info(f"Triage breakdown: {by_category}")

    return {
        "triaged_items": triaged_items,
        "relevant_items": relevant_items,
        "triage_stats": triage_stats,
        "metrics": {**state.get("metrics", {}), "triaged": len(triaged_items), "relevant": len(relevant_items)},
    }


# =============================================================================
# NODE: FETCH FULL CONTENT
# =============================================================================

async def fetch_full_content_node(state: NewsletterState) -> dict:
    """Fetch full-text content for relevant items."""
    items = state.get("relevant_items", [])
    if not items:
        logger.info("No relevant items - skipping full-text fetch")
        return {"relevant_items": items}

    catalog_path = Path(settings.sources_catalog_path)
    if not catalog_path.exists():
        catalog_path = Path(__file__).parent.parent.parent.parent / settings.sources_catalog_path
    catalog = load_source_catalog(catalog_path)
    trusted_domains = set(catalog.trusted_domains or [])

    def _domain_matches(domain: str) -> bool:
        if not domain:
            return False
        for trusted in trusted_domains:
            if domain == trusted or domain.endswith(f".{trusted}"):
                return True
        return False

    max_items = settings.max_full_text_items
    selected = items
    if max_items and len(items) > max_items:
        trusted_items = [item for item in items if _domain_matches(urlparse(item.raw_item.source_url).netloc)]
        remaining = [item for item in items if item not in trusted_items]
        remaining_sorted = sorted(remaining, key=lambda i: i.confidence, reverse=True)
        selected = (trusted_items + remaining_sorted)[:max_items]
        logger.info(
            "Full-text fetch capped",
            extra={"selected": len(selected), "total_relevant": len(items), "trusted": len(trusted_items)},
        )

    url_map: dict[str, list[str]] = {}
    for item in selected:
        url_map.setdefault(item.raw_item.source_url, []).append(item.raw_item.id)

    fetcher = ContentFetcher(
        timeout_seconds=settings.full_text_timeout_seconds,
        requests_per_minute=settings.full_text_requests_per_minute,
        max_concurrency=settings.full_text_max_concurrency,
        max_chars=settings.full_text_max_chars,
        min_chars=settings.full_text_min_chars,
    )

    urls = list(url_map.keys())
    logger.info(f"Fetching full-text content for {len(urls)} URLs")

    content_by_url, errors = await fetcher.fetch_many([(url, url) for url in urls])

    updated_relevant: list[TriagedItem] = []
    for item in items:
        raw = item.raw_item
        text = content_by_url.get(raw.source_url)
        if text:
            domain = urlparse(raw.source_url).netloc
            raw = raw.model_copy(update={"full_text": text, "full_text_source": domain})
            item = item.model_copy(update={"raw_item": raw})
        updated_relevant.append(item)

    updated_triaged: list[TriagedItem] = []
    for item in state.get("triaged_items", []):
        raw = item.raw_item
        text = content_by_url.get(raw.source_url)
        if text:
            domain = urlparse(raw.source_url).netloc
            raw = raw.model_copy(update={"full_text": text, "full_text_source": domain})
            item = item.model_copy(update={"raw_item": raw})
        updated_triaged.append(item)

    logger.info(
        "Full-text fetch complete",
        extra={
            "fetched": len(content_by_url),
            "errors": len(errors),
            "skipped": max(0, len(items) - len(selected)),
        },
    )

    return {
        "relevant_items": updated_relevant,
        "triaged_items": updated_triaged,
        "metrics": {
            **state.get("metrics", {}),
            "full_text_fetched": len(content_by_url),
            "full_text_failed": len(errors),
            "full_text_skipped": max(0, len(items) - len(selected)),
        },
    }


# =============================================================================
# NODE: DEDUPE
# =============================================================================

def dedupe_node(state: NewsletterState) -> dict:
    """Deduplicate relevant items after triage."""
    relevant_items = state.get("relevant_items", [])
    logger.info(f"Deduplicating {len(relevant_items)} relevant items...")

    agent = DedupeAgent(
        api_key=settings.gemini_api_key,
        model=settings.dedupe_model or settings.default_model,
        similarity_threshold=settings.dedupe_similarity_threshold,
    )

    if not relevant_items:
        stats = {"original": 0, "deduped": 0, "removed": 0}
        return {
            "deduped_items": [],
            "dedupe_stats": stats,
            "relevant_items": [],
            "metrics": {
                **state.get("metrics", {}),
                "deduped": 0,
                "dedupe_removed": 0,
            },
        }

    deduped_raw_items, stats = agent.dedupe_items([item.raw_item for item in relevant_items])
    deduped_ids = {item.id for item in deduped_raw_items}
    deduped_relevant = [item for item in relevant_items if item.raw_item.id in deduped_ids]

    logger.info(f"Dedupe complete: {stats.get('deduped', 0)} kept, {stats.get('removed', 0)} removed")

    return {
        "deduped_items": deduped_raw_items,
        "dedupe_stats": stats,
        "relevant_items": deduped_relevant,
        "metrics": {
            **state.get("metrics", {}),
            "deduped": stats.get("deduped", 0),
            "dedupe_removed": stats.get("removed", 0),
        },
    }


# =============================================================================
# NODE: ANALYZE
# =============================================================================

def analyze_node(state: NewsletterState) -> dict:
    """Deep analysis of relevant items."""
    full_text_count = sum(1 for item in state["relevant_items"] if item.raw_item.full_text)
    logger.info(
        f"Analyzing {len(state['relevant_items'])} relevant items (full text: {full_text_count})..."
    )

    prompt_context = None
    prompt_context_path = Path(settings.prompt_context_path)
    if not prompt_context_path.exists():
        prompt_context_path = Path(__file__).parent.parent.parent.parent / settings.prompt_context_path
    prompt_context = load_prompt_context(prompt_context_path)

    agent = AnalysisAgent(
        api_key=settings.gemini_api_key,
        model=settings.analysis_model or settings.default_model,
        portfolio_context=state["portfolio_context"],
        requests_per_minute=settings.llm_requests_per_minute,
        max_workers=settings.analysis_max_workers,
    )
    logger.info(
        f"Analysis agent configured (model={agent.model}, workers={agent.max_workers}, rpm={agent.requests_per_minute})"
    )

    def progress(completed: int, total: int) -> None:
        if completed % 5 == 0:
            logger.info(f"Analysis progress: {completed}/{total}")

    def build_context(item: TriagedItem) -> str | None:
        if not prompt_context:
            return None
        return build_item_context_for_analysis(
            portfolio_company=item.related_portfolio_company,
            competitors=item.related_competitors,
            prompt_context=prompt_context,
        )

    analyzed_items, carve_outs = agent.analyze_batch(
        state["relevant_items"],
        on_progress=progress,
        context_builder=build_context,
    )

    logger.info(f"Analysis complete: {len(analyzed_items)} items, {len(carve_outs)} carve-outs")

    return {
        "analyzed_items": analyzed_items,
        "carve_out_opportunities": carve_outs,
        "metrics": {
            **state.get("metrics", {}),
            "analyzed": len(analyzed_items),
            "carve_outs": len(carve_outs),
        },
    }


# =============================================================================
# NODE: CURATE
# =============================================================================

def curate_node(state: NewsletterState) -> dict:
    """Filter and cap analyzed items for a high-signal newsletter."""
    items = state.get("analyzed_items", [])
    carve_outs = state.get("carve_out_opportunities", [])

    if not items:
        return {"analyzed_items": [], "carve_out_opportunities": []}

    json_path = Path(settings.company_data_path)
    if not json_path.exists():
        json_path = Path(__file__).parent.parent.parent.parent / settings.company_data_path
    companies, clusters = load_company_context(json_path)
    company_lookup, cluster_lookup = build_company_lookups(companies, clusters)

    thresholds = state.get("relevance_thresholds", {})
    carve_out_ids = {
        co.source_item.triaged_item.raw_item.id
        for co in carve_outs
        if co.source_item and co.source_item.triaged_item
    }

    def _threshold_for(item: object) -> int:
        category = item.triaged_item.category.value
        return thresholds.get(category, settings.min_signal_score)

    filtered = [
        item
        for item in items
        if item.signal_score >= _threshold_for(item)
        or item.carve_out_potential in (CarveOutPotential.HIGH, CarveOutPotential.MEDIUM)
    ]

    def _top(items_in: list, limit: int) -> list:
        return sorted(items_in, key=lambda i: i.signal_score, reverse=True)[:limit]

    def _cap_by_group(
        items_in: list,
        group_fn,
        per_group: int,
        total_limit: int,
    ) -> list:
        sorted_items = sorted(items_in, key=lambda i: i.signal_score, reverse=True)
        grouped: dict[str, list] = {}
        for item in sorted_items:
            key = group_fn(item) or "Other"
            bucket = grouped.setdefault(key, [])
            if len(bucket) < per_group:
                bucket.append(item)

        group_order = sorted(
            grouped.items(),
            key=lambda kv: max(i.signal_score for i in kv[1]) if kv[1] else 0,
            reverse=True,
        )
        flattened: list = []
        for _, group_items in group_order:
            flattened.extend(group_items)

        if total_limit:
            flattened = flattened[:total_limit]
        return flattened

    by_category: dict[ItemCategory, list] = {
        ItemCategory.PORTFOLIO: [],
        ItemCategory.COMPETITOR: [],
        ItemCategory.MAJOR_DEAL: [],
        ItemCategory.INDUSTRY: [],
    }
    for item in filtered:
        by_category[item.triaged_item.category].append(item)

    selected = []
    portfolio_selected = _cap_by_group(
        by_category[ItemCategory.PORTFOLIO],
        lambda item: resolve_portfolio_company(item, company_lookup),
        settings.max_items_per_portfolio_company,
        settings.max_portfolio_items,
    )
    competitor_industry = by_category[ItemCategory.COMPETITOR] + by_category[ItemCategory.INDUSTRY]
    competitive_selected = _cap_by_group(
        competitor_industry,
        lambda item: resolve_cluster(item, company_lookup, cluster_lookup),
        settings.max_items_per_cluster,
        settings.max_competitor_items + settings.max_industry_items,
    )
    deals_selected = _cap_by_group(
        by_category[ItemCategory.MAJOR_DEAL],
        lambda item: resolve_cluster(item, company_lookup, cluster_lookup),
        settings.max_items_per_cluster,
        settings.max_deal_items,
    )

    selected.extend(portfolio_selected)
    selected.extend(competitive_selected)
    selected.extend(deals_selected)

    selected_ids = {item.triaged_item.raw_item.id for item in selected}
    for item in filtered:
        if item.triaged_item.raw_item.id in carve_out_ids and item.triaged_item.raw_item.id not in selected_ids:
            selected.append(item)
            selected_ids.add(item.triaged_item.raw_item.id)

    curated_carve_outs = [
        co for co in carve_outs if co.source_item.triaged_item.raw_item.id in selected_ids
    ]

    logger.info(
        "Curation complete",
        extra={
            "portfolio": len(portfolio_selected),
            "competitive": len(competitive_selected),
            "deals": len(deals_selected),
            "carve_outs": len(curated_carve_outs),
            "total_curated": len(selected),
        },
    )

    return {
        "analyzed_items": selected,
        "carve_out_opportunities": curated_carve_outs,
        "metrics": {
            **state.get("metrics", {}),
            "curated_total": len(selected),
            "curated_removed": max(0, len(items) - len(selected)),
        },
    }


# =============================================================================
# NODE: COMPOSE
# =============================================================================

def compose_node(state: NewsletterState) -> dict:
    """Compose the newsletter email."""
    logger.info("Composing newsletter...")

    agent = EmailComposerAgent(
        api_key=settings.gemini_api_key,
        model=settings.composer_model or settings.default_model,
    )

    newsletter, html = agent.compose_newsletter(
        analyzed_items=state["analyzed_items"],
        carve_outs=state["carve_out_opportunities"],
        total_processed=len(state.get("raw_items", [])),
    )

    logger.info(f"Newsletter composed: {newsletter.subject}")
    logger.info(
        "Newsletter section counts",
        extra={
            "portfolio": len(newsletter.portfolio_section.items),
            "competitive_cluster": len(newsletter.competitive_cluster_section.items),
            "deals": len(newsletter.deals_section.items),
            "carve_outs": len(newsletter.carve_out_section.items) if newsletter.carve_out_section else 0,
        },
    )

    return {
        "newsletter": newsletter,
        "newsletter_html": html,
        "completed_at": datetime.now(timezone.utc),
    }


# =============================================================================
# NODE: SAVE OUTPUT
# =============================================================================

def save_output_node(state: NewsletterState) -> dict:
    """Save newsletter to file."""
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save HTML
    html_path = output_dir / f"newsletter_{timestamp}.html"
    html_path.write_text(state["newsletter_html"])
    logger.info(f"Saved newsletter to {html_path}")

    # Save JSON summary
    summary = {
        "generated_at": state["completed_at"].isoformat() if state.get("completed_at") else None,
        "metrics": state.get("metrics", {}),
        "triage_stats": state.get("triage_stats", {}),
        "dedupe_stats": state.get("dedupe_stats", {}),
        "carve_out_count": len(state.get("carve_out_opportunities", [])),
        "newsletter_subject": state["newsletter"].subject if state.get("newsletter") else None,
    }
    json_path = output_dir / f"summary_{timestamp}.json"
    json_path.write_text(json.dumps(summary, indent=2, default=str))

    return {
        "metrics": {**state.get("metrics", {}), "output_path": str(html_path)},
    }


# =============================================================================
# NODE: SEND EMAIL
# =============================================================================

def send_email_node(state: NewsletterState) -> dict:
    """Send the newsletter email via SMTP when enabled."""
    if not settings.send_email:
        logger.info("Email sending disabled; skipping.")
        return {
            "metrics": {**state.get("metrics", {}), "email_status": "skipped"},
        }

    newsletter = state.get("newsletter")
    html = state.get("newsletter_html", "")
    if not newsletter or not html:
        error = "Email sending skipped: newsletter content missing."
        logger.warning(error)
        return {
            "errors": [*state.get("errors", []), error],
            "metrics": {**state.get("metrics", {}), "email_status": "skipped"},
        }

    from_email = settings.from_email.strip()
    to_emails = _split_emails(settings.to_email)
    if not from_email or not to_emails:
        error = "Email sending skipped: FROM_EMAIL or TO_EMAIL not configured."
        logger.warning(error)
        return {
            "errors": [*state.get("errors", []), error],
            "metrics": {**state.get("metrics", {}), "email_status": "skipped"},
        }

    if not settings.smtp_username or not settings.smtp_password:
        error = "Email sending skipped: SMTP credentials not configured."
        logger.warning(error)
        return {
            "errors": [*state.get("errors", []), error],
            "metrics": {**state.get("metrics", {}), "email_status": "skipped"},
        }

    sender = SmtpEmailSender(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_tls=settings.smtp_use_tls,
        use_ssl=settings.smtp_use_ssl,
        timeout_seconds=settings.smtp_timeout_seconds,
    )

    result = sender.send_html(
        subject=newsletter.subject,
        html=html,
        from_email=from_email,
        to_emails=to_emails,
    )

    if result.success:
        logger.info(
            "Email sent",
            extra={
                "recipients": len(to_emails),
                "message_id": result.message_id,
            },
        )
        return {
            "metrics": {
                **state.get("metrics", {}),
                "email_status": "sent",
                "email_message_id": result.message_id,
                "email_recipients": len(to_emails),
            },
        }

    error = f"Email send failed: {result.error or 'unknown error'}"
    logger.error(error)
    return {
        "errors": [*state.get("errors", []), error],
        "metrics": {
            **state.get("metrics", {}),
            "email_status": "failed",
            "email_error": result.error or "unknown error",
        },
    }
