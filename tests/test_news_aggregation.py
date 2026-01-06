"""Test news aggregation and show actual results."""

import asyncio
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from silvertree_newsletter.config import settings
from silvertree_newsletter.models.schemas import QueryType
from silvertree_newsletter.services.perplexity import PerplexityClient
from silvertree_newsletter.tools.company_context_loader import load_company_context
from silvertree_newsletter.tools.query_builder import build_search_queries


async def run_full_aggregation():
    """Run searches and aggregate results."""
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
    print(f"Loaded {len(companies)} companies, {len(clusters)} clusters")

    queries = build_search_queries(
        companies=companies,
        clusters=clusters,
        lookback_days=settings.search_lookback_days,
    )

    # Group queries by type
    by_type = defaultdict(list)
    for q in queries:
        by_type[q.query_type].append(q)

    print(f"\nGenerated {len(queries)} queries:")
    for qtype, qlist in by_type.items():
        print(f"  {qtype.value}: {len(qlist)}")

    # Run a sample of each type (to save API calls)
    sample_queries = []
    for qtype in [QueryType.PORTFOLIO, QueryType.GP_BULLHOUND, QueryType.COMPETITOR, QueryType.INDUSTRY]:
        type_queries = by_type.get(qtype, [])
        # Take 2 from each type
        sample_queries.extend(type_queries[:2])

    print(f"\n=== Running {len(sample_queries)} sample queries ===")
    print(f"(~{len(sample_queries) * 1.2:.0f}s estimated time at 50 RPM)\n")

    all_items = []
    items_by_type = defaultdict(list)
    items_by_company = defaultdict(list)

    def progress(completed: int, total: int) -> None:
        print(f"  [{completed}/{total}] queries completed...")

    results = await client.search_batch(sample_queries, on_progress=progress)

    for query, items, _error in results:
        all_items.extend(items)
        items_by_type[query.query_type].extend(items)
        if query.related_company:
            items_by_company[query.related_company].extend(items)

    # Print results
    print(f"\n{'='*60}")
    print(f"AGGREGATED NEWS RESULTS")
    print(f"{'='*60}")
    print(f"Total items: {len(all_items)}")
    print(f"\nBy query type:")
    for qtype, items in items_by_type.items():
        print(f"  {qtype.value}: {len(items)} items")

    print(f"\n{'='*60}")
    print("GP BULLHOUND RESULTS")
    print(f"{'='*60}")
    gp_items = items_by_type.get(QueryType.GP_BULLHOUND, [])
    if gp_items:
        for item in gp_items:
            print(f"\n  Title: {item.title}")
            print(f"  URL: {item.source_url}")
            print(f"  Source: {item.source}")
            if item.published_date:
                print(f"  Date: {item.published_date.strftime('%Y-%m-%d')}")
    else:
        print("  No GP Bullhound results found")
        print("  (Domain filter may be too restrictive or no recent content)")

    print(f"\n{'='*60}")
    print("ALL NEWS LINKS BY TYPE")
    print(f"{'='*60}")

    for qtype in [QueryType.PORTFOLIO, QueryType.COMPETITOR, QueryType.INDUSTRY]:
        items = items_by_type.get(qtype, [])
        print(f"\n--- {qtype.value.upper()} ({len(items)} items) ---")
        for item in items[:5]:  # Show first 5
            print(f"\n  {item.title[:70]}...")
            print(f"  {item.source_url}")
            print(f"  Source: {item.source}")

    # Save to JSON for inspection
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    output_data = {
        "generated_at": datetime.now().isoformat(),
        "total_items": len(all_items),
        "by_type": {k.value: len(v) for k, v in items_by_type.items()},
        "items": [
            {
                "title": item.title,
                "url": item.source_url,
                "source": item.source,
                "published_date": item.published_date.isoformat() if item.published_date else None,
                "related_companies": item.related_companies,
            }
            for item in all_items
        ],
    }
    output_file.write_text(json.dumps(output_data, indent=2))
    print(f"\n\nResults saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(run_full_aggregation())
