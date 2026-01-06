"""Test the Analysis Agent with carve-out detection."""

import json
from pathlib import Path
from datetime import datetime, timezone

from silvertree_newsletter.config import settings
from silvertree_newsletter.agents.triage_agent import TriageAgent
from silvertree_newsletter.agents.analysis_agent import AnalysisAgent
from silvertree_newsletter.workflow.state import RawNewsItem


def build_portfolio_context() -> str:
    """Build portfolio context from JSON file."""
    json_path = Path(settings.company_data_path)
    if not json_path.exists():
        json_path = Path(__file__).parent.parent / settings.company_data_path

    with open(json_path) as f:
        data = json.load(f)

    lines = ["SilverTree Equity Portfolio Companies:"]

    for company in data.get("companies", []):
        name = company.get("name", "")
        context = company.get("company_context", "")
        sector = company.get("sector", "")
        competitors = company.get("competitors_candidate", [])

        lines.append(f"\n• {name}")
        if context:
            lines.append(f"  {context}")
        if sector:
            lines.append(f"  Sector: {sector}")
        if competitors:
            lines.append(f"  Competitors: {', '.join(competitors[:5])}")

    lines.append("\n\nKey Sectors: CPG/TPM, Higher Ed SIS, Enterprise Architecture, Marketing Automation, KYC/CLM, Utilities")

    return "\n".join(lines)


def test_analysis():
    """Test analysis agent on triaged items."""
    # Test items - including one that should trigger carve-out detection
    test_items = [
        RawNewsItem(
            id="test1",
            title="Fenergo appoints new CFO and CRO to drive global expansion",
            summary="Fenergo, the leading provider of Client Lifecycle Management solutions, today announced key executive appointments. John Smith joins as CFO from Goldman Sachs, while Jane Doe takes on CRO role from Salesforce.",
            source="finextra",
            source_url="https://finextra.com/test1",
            published_date=datetime.now(timezone.utc),
        ),
        RawNewsItem(
            id="test2",
            title="LeanIX acquires enterprise architecture startup for $50M",
            summary="SAP-owned LeanIX has acquired smaller EA tools vendor to expand its application portfolio management capabilities. The acquisition brings 50 enterprise customers and a specialized cloud migration assessment tool.",
            source="techcrunch",
            source_url="https://techcrunch.com/test2",
            published_date=datetime.now(timezone.utc),
        ),
        RawNewsItem(
            id="test3",
            title="Large conglomerate announces strategic review of software division",
            summary="Industrial conglomerate XYZ Corp announced a strategic review of its non-core software assets, including its utility billing platform serving 200 utilities and its marketing automation tool. The company will focus on its core industrial equipment business. Bankers have been hired to explore options including sale or spin-off.",
            source="reuters",
            source_url="https://reuters.com/test3",
            published_date=datetime.now(timezone.utc),
        ),
    ]

    portfolio_context = build_portfolio_context()
    print(f"Portfolio context: {len(portfolio_context)} chars")

    # First, triage the items
    triage_agent = TriageAgent(
        api_key=settings.gemini_api_key,
        model=settings.default_model,
        portfolio_context=portfolio_context,
    )

    print("\n" + "=" * 70)
    print("STEP 1: TRIAGE")
    print("=" * 70)

    triaged_items = []
    for item in test_items:
        triaged = triage_agent.triage_item(item)
        triaged_items.append(triaged)
        print(f"\n{item.title[:50]}...")
        print(f"  → {triaged.category.value} | {triaged.deal_type.value} | Relevant: {triaged.is_relevant}")

    # Filter to relevant items only
    relevant_items = [t for t in triaged_items if t.is_relevant]
    print(f"\n{len(relevant_items)} of {len(triaged_items)} items are relevant")

    # Now analyze the relevant items
    analysis_agent = AnalysisAgent(
        api_key=settings.gemini_api_key,
        model=settings.default_model,
        portfolio_context=portfolio_context,
    )

    print("\n" + "=" * 70)
    print("STEP 2: DEEP ANALYSIS")
    print("=" * 70)

    analyzed_items, carve_outs = analysis_agent.analyze_batch(relevant_items)

    for analyzed in analyzed_items:
        print(f"\n{'=' * 50}")
        print(f"📰 {analyzed.triaged_item.raw_item.title[:60]}...")
        print(f"{'=' * 50}")
        print(f"\n📝 WHY IT MATTERS:")
        print(f"   {analyzed.why_it_matters}")

        print(f"\n📊 STRATEGIC IMPLICATIONS:")
        print(f"   {analyzed.strategic_implications[:300]}...")

        if analyzed.competitive_threat_level:
            print(f"\n⚔️  COMPETITIVE THREAT: {analyzed.competitive_threat_level}")
            print(f"   Affected: {', '.join(analyzed.affected_portfolio_companies)}")

        if analyzed.carve_out_potential.value not in ("none", "n/a"):
            print(f"\n🎯 CARVE-OUT POTENTIAL: {analyzed.carve_out_potential.value.upper()}")
            print(f"   Target Units: {', '.join(analyzed.carve_out_target_units)}")
            print(f"   Rationale: {analyzed.carve_out_rationale}")

    if carve_outs:
        print("\n" + "=" * 70)
        print("🚨 CARVE-OUT OPPORTUNITIES FLAGGED")
        print("=" * 70)
        for co in carve_outs:
            print(f"\n  Target: {co.target_company}")
            print(f"  Units: {', '.join(co.potential_units)}")
            print(f"  Priority: {co.priority}")
            print(f"  Fit: {co.strategic_fit_rationale[:200]}...")


if __name__ == "__main__":
    test_analysis()
