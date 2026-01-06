"""Test RSS collection and LLM relevance analysis."""

import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone

from silvertree_newsletter.config import settings
from silvertree_newsletter.services.rss_collector import RSSCollector, RSS_FEEDS
from silvertree_newsletter.services.perplexity import PerplexityClient
from silvertree_newsletter.models.schemas import SearchQuery, QueryType
from silvertree_newsletter.agents.relevance_analyzer import (
    RelevanceAnalyzer,
    build_portfolio_context,
)
from silvertree_newsletter.tools.company_context_loader import load_company_context


async def test_rss_collection():
    """Test RSS feed collection."""
    collector = RSSCollector(
        timeout_seconds=30.0,
        lookback_days=14,
        max_items_per_feed=20,
    )

    print("=" * 60)
    print("RSS FEED COLLECTION")
    print("=" * 60)

    all_items = []
    results = await collector.collect_all()

    for feed_name, items in results.items():
        print(f"\n{feed_name}: {len(items)} items")
        all_items.extend(items)
        if items:
            print(f"  Latest: {items[0].title[:60]}...")

    print(f"\n Total from RSS: {len(all_items)} items")
    return all_items


async def get_gp_bullhound_via_search():
    """Get GP Bullhound news via broad Perplexity search."""
    print("\n" + "=" * 60)
    print("GP BULLHOUND NEWS (via Perplexity search)")
    print("=" * 60)

    client = PerplexityClient(
        api_key=settings.perplexity_api_key,
        model=settings.perplexity_model,
        timeout_seconds=settings.request_timeout_seconds,
        max_items=10,
        recency_filter="week",
        lookback_days=7,
        keep_undated=True,
        requests_per_minute=settings.perplexity_rpm,
    )

    # Broad GP Bullhound search - NOT company specific
    gp_query = SearchQuery(
        id="gp_bullhound_broad",
        query_text="GP Bullhound M&A deals technology software investment news announcements",
        query_type=QueryType.GP_BULLHOUND,
        related_company=None,
        created_at=datetime.now(timezone.utc),
    )

    print(f"\nQuery: {gp_query.query_text}")
    items = await client.search(gp_query)
    print(f"Found {len(items)} items")

    for item in items[:5]:
        print(f"\n  Title: {item.title[:70]}...")
        print(f"  URL: {item.source_url}")
        print(f"  Source: {item.source}")

    return items


async def test_relevance_analysis(items):
    """Test LLM relevance analysis on collected items."""
    if not items:
        print("\nNo items to analyze")
        return

    print("\n" + "=" * 60)
    print("LLM RELEVANCE ANALYSIS TEST")
    print("=" * 60)

    # Load portfolio context
    json_path = Path(settings.company_data_path)
    if not json_path.exists():
        json_path = Path(__file__).parent.parent / settings.company_data_path

    with open(json_path) as f:
        data = json.load(f)

    portfolio_context = build_portfolio_context(
        data.get("companies", []),
        data.get("competitor_clusters", []),
    )

    print(f"\nPortfolio context length: {len(portfolio_context)} chars")

    # Initialize analyzer with Gemini
    analyzer = RelevanceAnalyzer(
        api_key=settings.gemini_api_key,
        model=settings.default_model,
    )

    # Analyze first 3 items (to save API calls)
    test_items = items[:3]
    print(f"\nAnalyzing {len(test_items)} items...")

    for i, item in enumerate(test_items):
        print(f"\n--- Item {i+1}: {item.title[:50]}... ---")
        analyzed = await analyzer.analyze_item(item, portfolio_context)

        print(f"  Relevant: {analyzed.is_relevant}")
        print(f"  Relevance Level: {analyzed.relevance_level.value}")
        print(f"  Deal Type: {analyzed.deal_type.value}")
        print(f"  Category: {analyzed.category.value}")
        print(f"  Explanation: {analyzed.relevance_explanation}")

        if analyzed.related_portfolio_companies:
            print(f"  Portfolio Companies: {analyzed.related_portfolio_companies}")
        if analyzed.related_competitors:
            print(f"  Competitors: {analyzed.related_competitors}")

        if analyzed.carve_out_potential.value not in ("none", "not_applicable"):
            print(f"  Carve-out Potential: {analyzed.carve_out_potential.value}")
            print(f"  Carve-out Rationale: {analyzed.carve_out_rationale}")


async def main():
    """Run full pipeline test."""
    all_news = []

    # 1. Collect from RSS feeds
    rss_items = await test_rss_collection()
    all_news.extend(rss_items)

    # 2. Get GP Bullhound news via broad search
    gp_items = await get_gp_bullhound_via_search()
    all_news.extend(gp_items)

    print("\n" + "=" * 60)
    print(f"TOTAL COLLECTED: {len(all_news)} news items")
    print("=" * 60)

    # 3. Run relevance analysis on a sample
    if all_news:
        # Take mix of items for analysis
        sample = all_news[:5]  # First 5 items
        await test_relevance_analysis(sample)

    # 4. Save all collected items
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"collected_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    output_data = {
        "generated_at": datetime.now().isoformat(),
        "total_items": len(all_news),
        "items": [
            {
                "title": item.title,
                "url": item.source_url,
                "source": item.source,
                "published_date": item.published_date.isoformat() if item.published_date else None,
                "summary": item.summary[:300],
            }
            for item in all_news
        ],
    }
    output_file.write_text(json.dumps(output_data, indent=2))
    print(f"\nSaved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
