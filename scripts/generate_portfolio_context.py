#!/usr/bin/env python3
"""Generate portfolio company context markdown files from JSON config.

This script reads company data from silvertree_companies_competitors.json
and carve-out criteria from prompt_context.json to generate structured
markdown files for each portfolio company.

Usage:
    python scripts/generate_portfolio_context.py
"""

import json
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    """Load JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_cluster_by_id(clusters: list[dict], cluster_id: str) -> dict | None:
    """Find cluster by ID."""
    for cluster in clusters:
        if cluster.get("cluster_id") == cluster_id:
            return cluster
    return None


def get_sector_playbook(prompt_context: dict, cluster_id: str) -> dict | None:
    """Get sector playbook from prompt context."""
    playbooks = prompt_context.get("sector_playbooks", {})
    return playbooks.get(cluster_id)


def get_portfolio_company_context(prompt_context: dict, company_id: str) -> dict | None:
    """Get portfolio company context from prompt context."""
    companies = prompt_context.get("portfolio_companies", [])
    for company in companies:
        if company.get("company_id") == company_id:
            return company
    return None


def format_competitor_table(competitors: list[str], competitor_type: str) -> str:
    """Format competitors as a markdown table."""
    if not competitors:
        return "_None identified_"

    lines = [
        "| Competitor | Type |",
        "|------------|------|",
    ]
    for comp in competitors[:8]:  # Limit to 8 competitors
        lines.append(f"| {comp} | {competitor_type} |")
    return "\n".join(lines)


def generate_company_markdown(
    company: dict,
    cluster: dict | None,
    playbook: dict | None,
    portfolio_context: dict | None,
    global_heuristics: dict | None,
) -> str:
    """Generate markdown content for a company."""
    name = company.get("name", "Unknown")
    aliases = company.get("aliases", [])
    sector = company.get("sector", "")
    company_context = company.get("company_context", "")
    websites = company.get("websites", [])
    direct_competitors = company.get("direct_competitors", [])
    indirect_competitors = company.get("indirect_competitors", [])

    # Get cluster info
    cluster_name = cluster.get("name", "") if cluster else ""
    cluster_description = cluster.get("what_it_is", "") if cluster else ""

    # Get portfolio company specific context
    core_thesis = ""
    strategic_priority = ""
    must_monitor = []
    if portfolio_context:
        core_thesis = portfolio_context.get("core_thesis", "")
        strategic_priority = portfolio_context.get("current_strategic_priority", "")
        must_monitor = portfolio_context.get("must_monitor_competitors", [])

    # Get ideal carve-out profile from playbook
    carveout_profile = {}
    if playbook:
        carveout_profile = playbook.get("ideal_carveout_profile", {})

    # Get global carve-out heuristics
    positive_signals = []
    negative_signals = []
    if global_heuristics:
        positive_signals = global_heuristics.get("strong_positive_signals", [])
        negative_signals = global_heuristics.get("strong_negative_signals", [])

    # Build markdown content
    lines = [
        f"# {name} - SilverTree Portfolio Company",
        "",
    ]

    # Company Overview
    lines.extend([
        "## Company Overview",
        "",
    ])
    if sector:
        lines.append(f"**Sector:** {sector}")
    if cluster_name:
        lines.append(f"**Market Segment:** {cluster_name}")
    if company_context:
        lines.append(f"**Core Business:** {company_context}")
    if aliases:
        lines.append(f"**Also Known As:** {', '.join(aliases)}")
    if websites:
        lines.append(f"**Website:** {websites[0]}")
    lines.append("")

    if cluster_description:
        lines.extend([
            "### Market Context",
            cluster_description,
            "",
        ])

    # Strategic Thesis
    if core_thesis or strategic_priority:
        lines.extend([
            "## Strategic Thesis",
            "",
        ])
        if core_thesis:
            lines.extend([
                "### Investment Thesis",
                core_thesis,
                "",
            ])
        if strategic_priority:
            lines.extend([
                "### Current Strategic Priority",
                strategic_priority,
                "",
            ])

    # Competitors
    lines.extend([
        "## Competitive Landscape",
        "",
    ])

    if must_monitor:
        lines.extend([
            "### Priority Competitors to Monitor",
            "",
            "| Rank | Competitor | Rationale |",
            "|------|------------|-----------|",
        ])
        for comp in must_monitor[:5]:
            rank = comp.get("rank", "-")
            comp_name = comp.get("name", "Unknown")
            why = comp.get("why", "")
            lines.append(f"| {rank} | {comp_name} | {why} |")
        lines.append("")

    if direct_competitors:
        lines.extend([
            "### Direct Competitors",
            "",
        ])
        lines.append(format_competitor_table(direct_competitors, "Direct"))
        lines.append("")

    if indirect_competitors:
        lines.extend([
            "### Indirect Competitors",
            "",
        ])
        lines.append(format_competitor_table(indirect_competitors, "Indirect"))
        lines.append("")

    # Ideal Carve-Out Profile
    if carveout_profile:
        lines.extend([
            "## Ideal Carve-Out Profile",
            "",
        ])

        asset_type = carveout_profile.get("asset_type", "")
        if asset_type:
            lines.append(f"**Target Asset Type:** {asset_type}")

        size_pref = carveout_profile.get("size_preference", {})
        if size_pref:
            arr = size_pref.get("arr_gbp", size_pref.get("revenue_gbp", ""))
            employees = size_pref.get("employee_range", "")
            if arr:
                lines.append(f"**ARR/Revenue Range (GBP):** {arr}")
            if employees:
                lines.append(f"**Employee Range:** {employees}")

        geo_pref = carveout_profile.get("geography_preference", [])
        if geo_pref:
            lines.append(f"**Geography Preference:** {', '.join(geo_pref)}")

        product_lines = carveout_profile.get("product_lines_of_interest", [])
        if product_lines:
            lines.append("")
            lines.append("### Product Lines of Interest")
            for product in product_lines:
                lines.append(f"- {product}")

        constraints = carveout_profile.get("integration_constraints", [])
        if constraints:
            lines.append("")
            lines.append("### Integration Constraints")
            for constraint in constraints:
                lines.append(f"- {constraint}")

        lines.append("")

    # Carve-Out Screening Criteria
    if positive_signals or negative_signals:
        lines.extend([
            "## Carve-Out Screening Criteria",
            "",
        ])

        if positive_signals:
            lines.extend([
                "### Strong Positive Signals",
                "",
            ])
            for signal in positive_signals:
                lines.append(f"- {signal}")
            lines.append("")

        if negative_signals:
            lines.extend([
                "### Strong Negative Signals",
                "",
            ])
            for signal in negative_signals:
                lines.append(f"- {signal}")
            lines.append("")

    return "\n".join(lines)


def main():
    """Generate portfolio context files."""
    # Determine paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    companies_path = project_root / "config" / "silvertree_companies_competitors.json"
    prompt_context_path = project_root / "config" / "prompt_context.json"
    output_dir = project_root / "config" / "portfolio_context"

    # Check files exist
    if not companies_path.exists():
        print(f"Error: Companies file not found at {companies_path}")
        sys.exit(1)

    # Load data
    print(f"Loading company data from {companies_path}")
    companies_data = load_json(companies_path)

    prompt_context = {}
    if prompt_context_path.exists():
        print(f"Loading prompt context from {prompt_context_path}")
        prompt_context = load_json(prompt_context_path)
    else:
        print(f"Warning: Prompt context file not found at {prompt_context_path}")

    # Get global guidelines
    global_guidelines = prompt_context.get("global_guidelines", {})
    global_heuristics = global_guidelines.get("carveout_screening_global_heuristics", {})

    # Get clusters and companies
    clusters = companies_data.get("competitor_clusters", [])
    companies = companies_data.get("companies", [])

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate files for each company
    generated_count = 0
    for company in companies:
        company_id = company.get("company_id", "").lower().replace("-", "_")
        if not company_id:
            continue

        cluster_id = company.get("cluster_id", "")
        cluster = get_cluster_by_id(clusters, cluster_id) if cluster_id else None
        playbook = get_sector_playbook(prompt_context, cluster_id) if cluster_id else None
        portfolio_context = get_portfolio_company_context(prompt_context, company.get("company_id", ""))

        markdown_content = generate_company_markdown(
            company=company,
            cluster=cluster,
            playbook=playbook,
            portfolio_context=portfolio_context,
            global_heuristics=global_heuristics,
        )

        # Write file
        output_path = output_dir / f"{company_id}.md"
        output_path.write_text(markdown_content, encoding="utf-8")
        print(f"Generated: {output_path.name}")
        generated_count += 1

    print(f"\nGenerated {generated_count} portfolio context files in {output_dir}")


if __name__ == "__main__":
    main()
