"""Test the Triage Agent."""

import json
from pathlib import Path
from datetime import datetime, timezone

from silvertree_newsletter.config import settings
from silvertree_newsletter.agents.triage_agent import TriageAgent
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


def test_triage():
    """Test triage on sample news items."""
    # Sample news items to test
    test_items = [
        RawNewsItem(
            id="test1",
            title="GTreasury acquires Solvexia",
            summary="Ripple-owned GTreasury has acquired Solvexia, a data-driven provider of reconciliation and compliance software.",
            source="finextra",
            source_url="https://finextra.com/test1",
            published_date=datetime.now(timezone.utc),
        ),
        RawNewsItem(
            id="test2",
            title="Fenergo appoints new CFO and CRO to drive global expansion",
            summary="Fenergo, the leading provider of Client Lifecycle Management solutions, today announced key executive appointments to accelerate growth.",
            source="finextra",
            source_url="https://finextra.com/test2",
            published_date=datetime.now(timezone.utc),
        ),
        RawNewsItem(
            id="test3",
            title="LeanIX acquires enterprise architecture startup for $50M",
            summary="SAP-owned LeanIX has acquired a smaller EA tools vendor to expand its application portfolio management capabilities.",
            source="techcrunch",
            source_url="https://techcrunch.com/test3",
            published_date=datetime.now(timezone.utc),
        ),
        RawNewsItem(
            id="test4",
            title="Narwal adds AI to its vacuum cleaners",
            summary="Narwal adds AI features to monitor pets and find dirt more efficiently.",
            source="techcrunch",
            source_url="https://techcrunch.com/test4",
            published_date=datetime.now(timezone.utc),
        ),
        RawNewsItem(
            id="test5",
            title="Major utility company signs 10-year deal with Kraken Technologies",
            summary="A major European utility has signed a decade-long platform deal with Octopus Energy's Kraken Technologies for billing and customer management.",
            source="utility_dive",
            source_url="https://utilitydive.com/test5",
            published_date=datetime.now(timezone.utc),
        ),
    ]

    portfolio_context = build_portfolio_context()
    print(f"Portfolio context: {len(portfolio_context)} chars")

    agent = TriageAgent(
        api_key=settings.gemini_api_key,
        model=settings.default_model,
        portfolio_context=portfolio_context,
    )

    print("\n" + "=" * 70)
    print("TRIAGE AGENT TEST")
    print("=" * 70)

    for item in test_items:
        print(f"\n--- {item.title[:50]}... ---")
        result = agent.triage_item(item)

        print(f"  Relevant: {result.is_relevant}")
        print(f"  Category: {result.category.value}")
        print(f"  Deal Type: {result.deal_type.value}")
        print(f"  Relevance: {result.relevance_level.value}")
        print(f"  Confidence: {result.confidence}%")
        if result.related_portfolio_company:
            print(f"  Portfolio Co: {result.related_portfolio_company}")
        if result.related_competitors:
            print(f"  Competitors: {result.related_competitors}")
        print(f"  Reason: {result.triage_reason}")


if __name__ == "__main__":
    test_triage()
