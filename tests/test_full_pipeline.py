"""End-to-end test of the newsletter pipeline."""

import asyncio
import logging
from pathlib import Path

from silvertree_newsletter.workflow import run_newsletter_workflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)


async def main():
    """Run the full newsletter pipeline."""
    print("=" * 70)
    print("SILVERTREE NEWSLETTER - FULL PIPELINE TEST")
    print("=" * 70)

    # Run the workflow
    final_state = await run_newsletter_workflow()

    # Print results
    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)

    metrics = final_state.get("metrics", {})
    print(f"\n📊 METRICS:")
    print(f"   RSS items collected: {metrics.get('rss_items', 0)}")
    print(f"   Search items collected: {metrics.get('search_items', 0)}")
    print(f"   Total triaged: {metrics.get('triaged', 0)}")
    print(f"   Relevant items: {metrics.get('relevant', 0)}")
    print(f"   Analyzed: {metrics.get('analyzed', 0)}")
    print(f"   Carve-outs flagged: {metrics.get('carve_outs', 0)}")

    triage_stats = final_state.get("triage_stats", {})
    if triage_stats:
        print(f"\n📋 TRIAGE BREAKDOWN:")
        for cat, count in triage_stats.get("by_category", {}).items():
            print(f"   {cat}: {count}")

    carve_outs = final_state.get("carve_out_opportunities", [])
    if carve_outs:
        print(f"\n🎯 CARVE-OUT OPPORTUNITIES:")
        for co in carve_outs:
            print(f"   • {co.target_company}: {', '.join(co.potential_units)}")
            print(f"     Priority: {co.priority}")

    newsletter = final_state.get("newsletter")
    if newsletter:
        print(f"\n📧 NEWSLETTER:")
        print(f"   Subject: {newsletter.subject}")
        print(f"   Portfolio items: {len(newsletter.portfolio_section.items)}")
        print(f"   Competitive cluster items: {len(newsletter.competitive_cluster_section.items)}")
        print(f"   Deal items: {len(newsletter.deals_section.items)}")

    output_path = metrics.get("output_path")
    if output_path:
        print(f"\n📁 OUTPUT:")
        print(f"   {output_path}")

        # Show first part of executive summary
        if newsletter:
            print(f"\n📝 EXECUTIVE SUMMARY:")
            print(f"   {newsletter.executive_summary[:500]}...")


if __name__ == "__main__":
    asyncio.run(main())
