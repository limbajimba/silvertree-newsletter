"""Deep Research Agent using Google Gemini Interactions API.

This agent uses Google's deep-research-pro-preview model via the Interactions API
to generate comprehensive carve-out dossiers with structured output.

Features:
- Async background execution with polling
- Structured JSON output schema
- Comprehensive research reports for M&A carve-out analysis
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from google import genai
from google.genai.types import (
    CreateInteractionConfig,
    InteractionState,
    Part,
    Schema,
    Type,
)

if TYPE_CHECKING:
    from silvertree_newsletter.workflow.state import CarveOutOpportunity

logger = logging.getLogger(__name__)


# Deep Research Model
DEEP_RESEARCH_MODEL = "deep-research-pro-preview-12-2025"


# Structured output schema for deep research results
DEEP_RESEARCH_OUTPUT_SCHEMA = Schema(
    type=Type.OBJECT,
    properties={
        "target_company_overview": Schema(
            type=Type.OBJECT,
            properties={
                "name": Schema(type=Type.STRING),
                "description": Schema(type=Type.STRING),
                "ownership": Schema(type=Type.STRING),
                "estimated_revenue": Schema(type=Type.STRING),
            },
        ),
        "verified_business_units": Schema(
            type=Type.ARRAY,
            items=Schema(
                type=Type.OBJECT,
                properties={
                    "unit_name": Schema(type=Type.STRING),
                    "products_services": Schema(type=Type.STRING),
                    "estimated_size": Schema(type=Type.STRING),
                    "carveout_fit": Schema(type=Type.STRING),
                },
            ),
        ),
        "separation_analysis": Schema(
            type=Type.OBJECT,
            properties={
                "complexity": Schema(type=Type.STRING, enum=["low", "medium", "high", "unknown"]),
                "drivers": Schema(type=Type.ARRAY, items=Schema(type=Type.STRING)),
                "entanglement_risks": Schema(type=Type.ARRAY, items=Schema(type=Type.STRING)),
                "timeline": Schema(type=Type.STRING),
            },
        ),
        "strategic_fit": Schema(
            type=Type.OBJECT,
            properties={
                "portfolio_company": Schema(type=Type.STRING),
                "thesis_alignment": Schema(type=Type.STRING),
                "recommendation": Schema(type=Type.STRING),
            },
        ),
        "comparable_deals": Schema(
            type=Type.ARRAY,
            items=Schema(
                type=Type.OBJECT,
                properties={
                    "deal": Schema(type=Type.STRING),
                    "valuation_context": Schema(type=Type.STRING),
                },
            ),
        ),
        "risks": Schema(type=Type.ARRAY, items=Schema(type=Type.STRING)),
        "diligence_questions": Schema(type=Type.ARRAY, items=Schema(type=Type.STRING)),
        "next_steps": Schema(type=Type.ARRAY, items=Schema(type=Type.STRING)),
        "confidence": Schema(type=Type.STRING, enum=["low", "medium", "high"]),
    },
)


DEEP_RESEARCH_PROMPT = """You are a senior private equity associate at SilverTree Equity conducting deep research on a potential carve-out opportunity.

## Research Target
Company: {target_company}
Deal Type: {deal_type}
Initial Assessment: {initial_rationale}

## Portfolio Company Context
{portfolio_context}

## Source Articles
{source_articles}

## Research Task
Conduct comprehensive research on this potential carve-out opportunity. Focus on:

1. **Target Company Overview**: Verify company details, ownership structure, and estimated revenue/ARR
2. **Business Units Analysis**: Identify distinct business units/product lines and assess carve-out fit for each
3. **Separation Analysis**: Evaluate separation complexity, key drivers (data, people, contracts, infrastructure), entanglement risks, and realistic timeline
4. **Strategic Fit**: How does this align with SilverTree's portfolio company ({portfolio_company}) and investment thesis?
5. **Comparable Deals**: Find 2-3 recent comparable transactions with valuation context
6. **Risks**: Identify key risks and constraints for this carve-out
7. **Diligence Questions**: List specific questions to validate feasibility
8. **Next Steps**: Recommend immediate actions

Be factual and cite sources. If information is unavailable, state "unknown" rather than speculating.
"""


@dataclass
class DeepResearchResult:
    """Result from deep research API call."""

    target_company: str
    success: bool
    data: dict = field(default_factory=dict)
    error: str | None = None
    research_time_seconds: float = 0.0
    sources_used: list[str] = field(default_factory=list)


@dataclass
class DeepResearchCarveOutAgent:
    """Deep research agent for comprehensive carve-out analysis."""

    api_key: str
    poll_interval_seconds: int = 30
    max_wait_minutes: int = 45
    max_retries: int = 2

    def __post_init__(self) -> None:
        self.client = genai.Client(api_key=self.api_key)

    async def research_carve_out(
        self,
        carve_out: "CarveOutOpportunity",
        portfolio_context: str = "",
    ) -> DeepResearchResult:
        """Execute deep research for a single carve-out opportunity.

        Args:
            carve_out: The carve-out opportunity to research
            portfolio_context: Portfolio company context markdown

        Returns:
            DeepResearchResult with structured research data
        """
        target_company = carve_out.target_company
        start_time = datetime.now(timezone.utc)

        # Build source articles summary
        source_articles = self._build_source_articles(carve_out)

        # Get portfolio company
        portfolio_company = ""
        if carve_out.source_item and carve_out.source_item.triaged_item:
            portfolio_company = carve_out.source_item.triaged_item.related_portfolio_company or ""

        # Build research prompt
        prompt = DEEP_RESEARCH_PROMPT.format(
            target_company=target_company,
            deal_type=carve_out.source_item.triaged_item.deal_type.value if carve_out.source_item else "unknown",
            initial_rationale=carve_out.strategic_fit_rationale or carve_out.source_item.why_it_matters if carve_out.source_item else "",
            portfolio_context=portfolio_context or "No specific portfolio context available.",
            source_articles=source_articles,
            portfolio_company=portfolio_company or "relevant portfolio company",
        )

        try:
            result = await self._execute_deep_research(prompt, target_company)

            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            result.research_time_seconds = elapsed

            return result

        except Exception as e:
            logger.error(f"Deep research failed for {target_company}: {e}")
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            return DeepResearchResult(
                target_company=target_company,
                success=False,
                error=str(e),
                research_time_seconds=elapsed,
            )

    async def _execute_deep_research(
        self,
        prompt: str,
        target_company: str,
    ) -> DeepResearchResult:
        """Execute the deep research API call with polling."""

        # Create interaction with background=True for async execution
        config = CreateInteractionConfig(
            model=DEEP_RESEARCH_MODEL,
            response_schema=DEEP_RESEARCH_OUTPUT_SCHEMA,
            output_mode="no_chunking",
        )

        logger.info(f"Starting deep research for: {target_company}")

        # Create the interaction
        interaction = self.client.aio.interactions.create(
            config=config,
        )

        # Send the research prompt
        interaction_result = await interaction

        # Send user message and start research
        response = await self.client.aio.interactions.send_message(
            interaction_id=interaction_result.name,
            message=Part.from_text(prompt),
            background=True,
        )

        # Poll for completion
        max_polls = (self.max_wait_minutes * 60) // self.poll_interval_seconds
        poll_count = 0
        sources_used = []

        while poll_count < max_polls:
            await asyncio.sleep(self.poll_interval_seconds)
            poll_count += 1

            # Get interaction status
            status = await self.client.aio.interactions.get(name=interaction_result.name)

            logger.debug(f"Deep research poll {poll_count}/{max_polls}: state={status.state}")

            if status.state == InteractionState.COMPLETED:
                # Extract result from final response
                if status.response and status.response.candidates:
                    candidate = status.response.candidates[0]
                    if candidate.content and candidate.content.parts:
                        text = candidate.content.parts[0].text
                        data = self._parse_response(text)

                        # Try to extract sources from grounding metadata
                        if hasattr(candidate, "grounding_metadata") and candidate.grounding_metadata:
                            if hasattr(candidate.grounding_metadata, "web_search_queries"):
                                sources_used = list(candidate.grounding_metadata.web_search_queries or [])

                        return DeepResearchResult(
                            target_company=target_company,
                            success=True,
                            data=data,
                            sources_used=sources_used,
                        )

                return DeepResearchResult(
                    target_company=target_company,
                    success=False,
                    error="No response content in completed interaction",
                )

            elif status.state == InteractionState.FAILED:
                error_msg = "Deep research interaction failed"
                if hasattr(status, "error") and status.error:
                    error_msg = str(status.error)
                return DeepResearchResult(
                    target_company=target_company,
                    success=False,
                    error=error_msg,
                )

            elif status.state == InteractionState.CANCELLED:
                return DeepResearchResult(
                    target_company=target_company,
                    success=False,
                    error="Deep research interaction was cancelled",
                )

        # Timeout
        return DeepResearchResult(
            target_company=target_company,
            success=False,
            error=f"Deep research timed out after {self.max_wait_minutes} minutes",
        )

    def _build_source_articles(self, carve_out: "CarveOutOpportunity") -> str:
        """Build source articles summary from carve-out sources."""
        source_items = carve_out.source_items or [carve_out.source_item] if carve_out.source_item else []

        articles = []
        for item in source_items[:5]:  # Limit to 5 sources
            raw = item.triaged_item.raw_item
            article = f"**{raw.title}**\n"
            article += f"Source: {raw.source}\n"
            article += f"URL: {raw.source_url}\n"
            if raw.published_date:
                article += f"Date: {raw.published_date.strftime('%Y-%m-%d')}\n"
            article += f"Summary: {raw.summary}\n"
            if raw.full_text:
                # Include truncated full text
                full_text = raw.full_text[:2000] + "..." if len(raw.full_text) > 2000 else raw.full_text
                article += f"Content: {full_text}\n"
            articles.append(article)

        return "\n---\n".join(articles) if articles else "No source articles available."

    def _parse_response(self, text: str) -> dict:
        """Parse JSON response from deep research."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1]).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return {}

    async def generate_report_async(
        self,
        carve_outs: list["CarveOutOpportunity"],
        portfolio_contexts: dict[str, str] | None = None,
        on_progress: callable | None = None,
    ) -> tuple[str, list[DeepResearchResult]]:
        """Generate comprehensive research report for multiple carve-outs.

        Args:
            carve_outs: List of carve-out opportunities to research
            portfolio_contexts: Dict mapping portfolio company names to context markdown
            on_progress: Optional callback(completed, total) for progress updates

        Returns:
            Tuple of (markdown_report, list of DeepResearchResult)
        """
        if not carve_outs:
            return "", []

        results: list[DeepResearchResult] = []
        portfolio_contexts = portfolio_contexts or {}

        for idx, carve_out in enumerate(carve_outs):
            # Get relevant portfolio context
            portfolio_company = ""
            if carve_out.source_item and carve_out.source_item.triaged_item:
                portfolio_company = carve_out.source_item.triaged_item.related_portfolio_company or ""

            context = portfolio_contexts.get(portfolio_company, "")
            if not context:
                # Try variations
                for key in portfolio_contexts:
                    if key.lower() in portfolio_company.lower() or portfolio_company.lower() in key.lower():
                        context = portfolio_contexts[key]
                        break

            result = await self.research_carve_out(carve_out, context)
            results.append(result)

            if on_progress:
                on_progress(idx + 1, len(carve_outs))

            logger.info(
                f"Deep research completed for {carve_out.target_company}: "
                f"success={result.success}, time={result.research_time_seconds:.1f}s"
            )

        # Generate markdown report
        report = self._render_markdown_report(carve_outs, results)
        return report, results

    def _render_markdown_report(
        self,
        carve_outs: list["CarveOutOpportunity"],
        results: list[DeepResearchResult],
    ) -> str:
        """Render deep research results as markdown report."""
        now = datetime.now(timezone.utc)
        lines = [
            "# Carve-Out Deep Research Dossier",
            "",
            f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}",
            f"Total opportunities analyzed: {len(carve_outs)}",
            "",
        ]

        for carve_out, result in zip(carve_outs, results):
            lines.append(f"## {carve_out.target_company}")
            lines.append(f"**Priority:** {carve_out.priority.upper()}")
            lines.append(f"**Research Status:** {'Completed' if result.success else 'Failed'}")
            lines.append(f"**Research Time:** {result.research_time_seconds:.1f} seconds")

            if not result.success:
                lines.append(f"**Error:** {result.error or 'Unknown error'}")
                lines.append("")
                # Fall back to basic info
                lines.append("### Basic Information (from initial analysis)")
                lines.append(f"- Potential units: {', '.join(carve_out.potential_units) if carve_out.potential_units else 'Unknown'}")
                lines.append(f"- Strategic fit: {carve_out.strategic_fit_rationale or 'See source article'}")
                lines.append("")
                continue

            data = result.data
            lines.append("")

            # Target Company Overview
            overview = data.get("target_company_overview", {})
            if overview:
                lines.append("### Target Overview")
                if overview.get("description"):
                    lines.append(f"- **Description:** {overview['description']}")
                if overview.get("ownership"):
                    lines.append(f"- **Ownership:** {overview['ownership']}")
                if overview.get("estimated_revenue"):
                    lines.append(f"- **Estimated Revenue:** {overview['estimated_revenue']}")
                lines.append("")

            # Verified Business Units
            units = data.get("verified_business_units", [])
            if units:
                lines.append("### Verified Business Units")
                for unit in units[:5]:  # Limit to 5
                    unit_name = unit.get("unit_name", "Unknown")
                    products = unit.get("products_services", "")
                    size = unit.get("estimated_size", "")
                    fit = unit.get("carveout_fit", "")
                    lines.append(f"- **{unit_name}**")
                    if products:
                        lines.append(f"  - Products/Services: {products}")
                    if size:
                        lines.append(f"  - Estimated Size: {size}")
                    if fit:
                        lines.append(f"  - Carve-out Fit: {fit}")
                lines.append("")

            # Separation Analysis
            separation = data.get("separation_analysis", {})
            if separation:
                lines.append("### Separation Analysis")
                lines.append("")
                lines.append("| Aspect | Assessment |")
                lines.append("|--------|------------|")
                lines.append(f"| Complexity | {separation.get('complexity', 'Unknown')} |")
                lines.append(f"| Timeline | {separation.get('timeline', 'Unknown')} |")

                drivers = separation.get("drivers", [])
                if drivers:
                    lines.append(f"| Key Drivers | {', '.join(drivers[:5])} |")

                risks = separation.get("entanglement_risks", [])
                if risks:
                    lines.append("")
                    lines.append("**Entanglement Risks:**")
                    for risk in risks[:5]:
                        lines.append(f"- {risk}")
                lines.append("")

            # Strategic Fit
            strategic_fit = data.get("strategic_fit", {})
            if strategic_fit:
                lines.append("### Strategic Fit")
                if strategic_fit.get("portfolio_company"):
                    lines.append(f"- **Related Portfolio Company:** {strategic_fit['portfolio_company']}")
                if strategic_fit.get("thesis_alignment"):
                    lines.append(f"- **Thesis Alignment:** {strategic_fit['thesis_alignment']}")
                if strategic_fit.get("recommendation"):
                    lines.append(f"- **Recommendation:** {strategic_fit['recommendation']}")
                lines.append("")

            # Comparable Deals
            comparables = data.get("comparable_deals", [])
            if comparables:
                lines.append("### Comparable Deals")
                for comp in comparables[:3]:
                    deal = comp.get("deal", "Unknown")
                    valuation = comp.get("valuation_context", "")
                    lines.append(f"- **{deal}**")
                    if valuation:
                        lines.append(f"  - {valuation}")
                lines.append("")

            # Risks
            risks = data.get("risks", [])
            if risks:
                lines.append("### Key Risks")
                for risk in risks[:5]:
                    lines.append(f"- {risk}")
                lines.append("")

            # Diligence Questions
            questions = data.get("diligence_questions", [])
            if questions:
                lines.append("### Diligence Questions")
                for question in questions[:5]:
                    lines.append(f"- {question}")
                lines.append("")

            # Next Steps
            next_steps = data.get("next_steps", [])
            if next_steps:
                lines.append("### Recommended Next Steps")
                for step in next_steps[:3]:
                    lines.append(f"- {step}")
                lines.append("")

            # Sources
            if carve_out.source_items or carve_out.source_item:
                source_items = carve_out.source_items or [carve_out.source_item]
                lines.append("### Sources")
                for item in source_items:
                    raw = item.triaged_item.raw_item
                    lines.append(f"- [{raw.title}]({raw.source_url})")
                lines.append("")

            # Confidence
            confidence = data.get("confidence", "medium")
            lines.append(f"**Confidence Level:** {confidence.upper()}")
            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)
