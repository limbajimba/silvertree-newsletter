"""Test Perplexity search functionality."""

import asyncio
import logging
from pathlib import Path

from silvertree_newsletter.config import settings
from silvertree_newsletter.models.schemas import QueryType
from silvertree_newsletter.services.perplexity import PerplexityClient
from silvertree_newsletter.tools.company_context_loader import load_company_context
from silvertree_newsletter.tools.query_builder import build_search_queries

logging.basicConfig(level=logging.INFO)


async def test_single_search():
    """Test a single Perplexity search."""
    client = PerplexityClient(
        api_key=settings.perplexity_api_key,
        model=settings.perplexity_model,
        timeout_seconds=settings.request_timeout_seconds,
        max_items=settings.perplexity_max_items,
        recency_filter="week",
        lookback_days=settings.search_lookback_days,
        keep_undated=settings.keep_undated_items,
        requests_per_minute=settings.perplexity_rpm,
        max_retries=settings.perplexity_max_retries,
    )

    json_path = Path(settings.company_data_path)
    if not json_path.exists():
        json_path = Path(__file__).parent.parent / settings.company_data_path

    companies, clusters = load_company_context(json_path)
    print(f"Loaded {len(companies)} companies and {len(clusters)} clusters")

    queries = build_search_queries(
        companies=companies,
        clusters=clusters,
        lookback_days=settings.search_lookback_days,
        max_company_terms=3,
        max_competitors=2,
        max_event_terms=4,
    )
    print(f"Generated {len(queries)} search queries")

    query_types = {}
    for q in queries:
        query_types[q.query_type] = query_types.get(q.query_type, 0) + 1
    print(f"Query breakdown: {query_types}")

    portfolio_query = next((q for q in queries if q.query_type == QueryType.PORTFOLIO), None)
    if portfolio_query:
        print(f"\n--- Testing PORTFOLIO query ---")
        print(f"Company: {portfolio_query.related_company}")
        print(f"Query: {portfolio_query.query_text[:200]}...")

        try:
            results = await client.search(portfolio_query)
            print(f"Found {len(results)} news items")
            for item in results[:3]:
                print(f"  - {item.title[:80]}...")
                print(f"    Source: {item.source}")
                print(f"    URL: {item.source_url[:60]}...")
                if item.published_date:
                    print(f"    Date: {item.published_date}")
        except Exception as e:
            print(f"Error: {e}")

    gp_query = next((q for q in queries if q.query_type == QueryType.GP_BULLHOUND), None)
    if gp_query:
        print(f"\n--- Testing GP_BULLHOUND query ---")
        print(f"Company: {gp_query.related_company}")
        print(f"Query: {gp_query.query_text[:200]}...")

        try:
            results = await client.search(gp_query)
            print(f"Found {len(results)} news items")
            for item in results[:3]:
                print(f"  - {item.title[:80]}...")
                print(f"    Source: {item.source}")
        except Exception as e:
            print(f"Error: {e}")

    industry_query = next((q for q in queries if q.query_type == QueryType.INDUSTRY), None)
    if industry_query:
        print(f"\n--- Testing INDUSTRY query ---")
        print(f"Sector: {industry_query.related_sector}")
        print(f"Query: {industry_query.query_text[:200]}...")

        try:
            results = await client.search(industry_query)
            print(f"Found {len(results)} news items")
            for item in results[:3]:
                print(f"  - {item.title[:80]}...")
                print(f"    Source: {item.source}")
        except Exception as e:
            print(f"Error: {e}")

    competitor_query = next((q for q in queries if q.query_type == QueryType.COMPETITOR), None)
    if competitor_query:
        print(f"\n--- Testing COMPETITOR query ---")
        print(f"Related to: {competitor_query.related_company}")
        print(f"Query: {competitor_query.query_text[:200]}...")

        try:
            results = await client.search(competitor_query)
            print(f"Found {len(results)} news items")
            for item in results[:3]:
                print(f"  - {item.title[:80]}...")
                print(f"    Source: {item.source}")
                print(f"    URL: {item.source_url[:60]}...")
        except Exception as e:
            print(f"Error: {e}")

    fenergo_query = next(
        (q for q in queries if q.related_company == "Fenergo" and q.query_type == QueryType.PORTFOLIO),
        None,
    )
    if fenergo_query:
        print(f"\n--- Testing Fenergo PORTFOLIO query ---")
        print(f"Query: {fenergo_query.query_text[:200]}...")

        try:
            results = await client.search(fenergo_query)
            print(f"Found {len(results)} news items")
            for item in results[:3]:
                print(f"  - {item.title[:80]}...")
                print(f"    Source: {item.source}")
        except Exception as e:
            print(f"Error: {e}")


async def test_batch_search():
    """Test batch search with rate limiting."""
    client = PerplexityClient(
        api_key=settings.perplexity_api_key,
        model=settings.perplexity_model,
        timeout_seconds=settings.request_timeout_seconds,
        max_items=settings.perplexity_max_items,
        recency_filter="week",
        lookback_days=settings.search_lookback_days,
        keep_undated=settings.keep_undated_items,
        requests_per_minute=settings.perplexity_rpm,
        max_retries=settings.perplexity_max_retries,
    )

    json_path = Path(settings.company_data_path)
    if not json_path.exists():
        json_path = Path(__file__).parent.parent / settings.company_data_path

    companies, clusters = load_company_context(json_path)
    queries = build_search_queries(
        companies=companies,
        clusters=clusters,
        lookback_days=settings.search_lookback_days,
    )

    # Test with first 5 queries only (to save API calls)
    test_queries = queries[:5]
    print(f"\n=== Testing batch search with {len(test_queries)} queries ===")
    print(f"Rate limit: {settings.perplexity_rpm} RPM ({60/settings.perplexity_rpm:.1f}s between requests)")

    def progress(completed: int, total: int) -> None:
        print(f"Progress: {completed}/{total} queries completed")

    results = await client.search_batch(test_queries, on_progress=progress)

    total_items = 0
    for query, items, _error in results:
        total_items += len(items)
        print(f"  {query.query_type.value}: {len(items)} items for {query.related_company}")

    print(f"\nTotal: {total_items} news items from {len(test_queries)} queries")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "batch":
        asyncio.run(test_batch_search())
    else:
        asyncio.run(test_single_search())
