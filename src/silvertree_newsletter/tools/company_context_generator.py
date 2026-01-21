import json
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def generate_company_context_files(
    config_path: str = "config/silvertree_companies_competitors.json",
    output_dir: str = "data/context/portcos"
) -> None:
    """
    Reads the company configuration and generates individual Markdown context files
    for each portfolio company to be used by the Deep Research Agent.
    """
    try:
        with open(config_path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Config file not found: {config_path}")
        return

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    companies = data.get("companies", [])
    clusters = {c["cluster_id"]: c for c in data.get("competitor_clusters", [])}

    for company in companies:
        company_name = company.get("name")
        company_id = company.get("company_id")
        
        if not company_name or not company_id:
            continue

        filename = output_path / f"{company_id}.md"
        
        # Get cluster info
        cluster_id = company.get("cluster_id")
        cluster_info = clusters.get(cluster_id, {})

        # Build Markdown Content
        content = []
        content.append(f"# Portfolio Company Context: {company_name}")
        content.append("")
        content.append(f"**Sector:** {company.get('sector', 'N/A')}")
        content.append(f"**Context:** {company.get('company_context', 'N/A')}")
        
        websites = company.get("websites", [])
        if websites:
            content.append(f"**Websites:** {', '.join(websites)}")
        
        content.append("")
        content.append("## Investment Thesis & Focus")
        # Assuming thesis is implied by context + sector, or we can add a placeholder for manual enrichment
        content.append(f"SilverTree invested in {company_name} to capitalize on the {company.get('sector')} market.")
        content.append(f"Primary focus: {cluster_info.get('what_it_is', 'N/A')}")

        content.append("")
        content.append("## Competitive Landscape")
        content.append(f"**Cluster:** {cluster_info.get('name', 'N/A')}")
        
        direct_competitors = company.get("direct_competitors", [])
        if direct_competitors:
            content.append("")
            content.append("### Direct Competitors")
            for comp in direct_competitors:
                content.append(f"- {comp}")

        indirect_competitors = company.get("indirect_competitors", [])
        if indirect_competitors:
            content.append("")
            content.append("### Indirect / Potential Competitors")
            for comp in indirect_competitors:
                content.append(f"- {comp}")

        content.append("")
        content.append("## Carve-Out Interest Areas")
        content.append("Key areas of interest for bolt-on acquisitions or carve-outs include:")
        tags = company.get("competitor_cluster_tags", [])
        for tag in tags:
            content.append(f"- {tag}")

        search_seeds = company.get("search_query_seeds", {})
        product_terms = search_seeds.get("product_terms", [])
        if product_terms:
            content.append("")
            content.append("### Key Product/Technology Keywords")
            for term in product_terms:
                content.append(f"- {term}")

        # Write file
        with open(filename, "w") as f:
            f.write("\n".join(content))
        
        logger.info(f"Generated context file: {filename}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    generate_company_context_files()
