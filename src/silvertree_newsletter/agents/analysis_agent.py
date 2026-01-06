"""Analysis Agent - Deep analysis of relevant news items.

This agent processes only RELEVANT items (filtered by triage) and performs:
1. In-depth strategic analysis
2. "Why It Matters" writeup for newsletter
3. Carve-out detection for M&A deals
4. Competitive threat assessment

Quality over speed - this is the PE-grade analysis.
"""

from __future__ import annotations

import json
import re
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import google.generativeai as genai

from silvertree_newsletter.workflow.state import (
    TriagedItem,
    AnalyzedItem,
    CarveOutOpportunity,
    CarveOutPotential,
)

logger = logging.getLogger(__name__)


# =============================================================================
# ANALYSIS PROMPTS
# =============================================================================

ANALYSIS_SYSTEM_PROMPT = """You are a senior analyst at SilverTree Equity, a private equity firm specializing in B2B software.

Your job is to provide PE-grade analysis of news items that have been flagged as relevant to SilverTree's portfolio.

## SilverTree Portfolio Context
{portfolio_context}

## Your Analysis Must Include:
Use the full source content if provided; prefer it over the short summary when they differ.

### For ALL relevant items:
1. **Why It Matters** (2-3 sentences): Write a clear, actionable summary explaining:
   - What happened
   - Why it matters to SilverTree
   - What action (if any) should be considered

2. **Strategic Implications**: Deeper analysis of:
   - Market positioning changes
   - Competitive dynamics
   - Potential impact on portfolio companies

3. **Impact on SilverTree** (1 sentence):
   - Explicitly state the impact on SilverTree or its portfolio (e.g., competitive threat, tailwind, pricing pressure, carve-out signal).

### For COMPETITOR news:
4. **Competitive Threat Assessment**:
   - Threat level: "high", "medium", or "low"
   - Which portfolio companies are affected
   - How this changes the competitive landscape

### For M&A DEALS (acquisitions, mergers, divestitures):
5. **Carve-Out Screening** - This is critical for PE:

   Only mark carve-out potential when the title/summary explicitly signals it.
   Look for signals that parts of the deal could be carve-out opportunities:
   - "Non-core" assets or divisions mentioned
   - Business units being "rationalized" or "streamlined"
   - Product lines outside the acquirer's focus
   - Divisions with different customer bases
   - Geographic units that don't fit
   - Legacy products being deprioritized

   Assess carve-out potential:
   - `high`: Clear non-core unit identified, strategic fit for SilverTree
   - `medium`: Possible opportunity, worth monitoring
   - `low`: Unlikely but noted
   - `none`: No carve-out potential
   - `n/a`: Not an M&A deal

   If potential exists, specify:
   - Target units that could be carved out (max 3-5 items, concise noun phrases, no repetition)
   - Why they might be available (tie to explicit evidence)
   - Strategic fit rationale for SilverTree (1-2 sentences, <= 60 words, no repetition)

6. **Signal Strength**:
   - Provide a `signal_score` (0-100) based on actionability and evidence.
   - Use any scoring rubric provided in context (base score + adjustments).
   - Provide `evidence` as short bullet phrases pulled from the title/summary.
   - Job postings, listicles, or generic educational content should score <= 20.

## Output Format
Respond with ONLY a JSON object:
```json
{{
    "why_it_matters": "2-3 sentence summary for newsletter",
    "strategic_implications": "Deeper analysis paragraph",
    "impact_on_silvertree": "Single sentence impact line",
    "competitive_threat_level": "high" | "medium" | "low" | null,
    "affected_portfolio_companies": ["Company1", "Company2"],
    "carve_out_potential": "high" | "medium" | "low" | "none" | "n/a",
    "carve_out_rationale": "Explanation of carve-out opportunity or why none exists",
    "carve_out_target_units": ["Unit1", "Unit2"],
    "key_entities": {{"Entity Name": "role (acquirer/target/investor/etc)"}},
    "signal_score": 0-100,
    "evidence": ["short phrase 1", "short phrase 2"]
}}
```

Be specific and evidence-based. Reference actual companies and competitive dynamics.
For carve-outs, think like a PE dealmaker - what non-core assets might become available?
If the summary lacks evidence, say so and set carve_out_potential to "none" or "n/a".
"""


ANALYSIS_USER_PROMPT = """Analyze this news item:

**Title:** {title}
**Source:** {source}
**Date:** {date}
**URL:** {url}
**Summary:** {summary}
**Full Source Content (if available):** {full_text}

**Triage Results:**
- Category: {category}
- Deal Type: {deal_type}
- Related Portfolio Company: {portfolio_company}
- Related Competitors: {competitors}
- Triage Reason: {triage_reason}

Provide your PE-grade analysis as JSON."""


# =============================================================================
# ANALYSIS AGENT
# =============================================================================

@dataclass
class AnalysisAgent:
    """Deep analysis agent for relevant news items."""

    api_key: str
    model: str = "gemini-2.5-flash"
    portfolio_context: str = ""
    requests_per_minute: int = 0
    max_workers: int = 1

    def __post_init__(self) -> None:
        genai.configure(api_key=self.api_key)
        self.client = genai.GenerativeModel(self.model)
        self._thread_local = threading.local()
        self._rate_limiter = RateLimiter(self.requests_per_minute) if self.requests_per_minute else None

    def analyze_item(self, item: TriagedItem, item_context: str | None = None) -> AnalyzedItem:
        """Perform deep analysis on a triaged item."""
        prompt = self._build_prompt(item, item_context)

        try:
            if self._rate_limiter:
                self._rate_limiter.wait()
            response = self._get_client().generate_content(prompt)
            result = self._parse_response(response.text)
            return self._build_analyzed_item(item, result)
        except Exception as e:
            logger.error(f"Analysis failed for {item.raw_item.id}: {e}")
            return self._build_default_analyzed_item(item)

    def analyze_batch(
        self,
        items: list[TriagedItem],
        on_progress: callable | None = None,
        context_builder: callable | None = None,
    ) -> tuple[list[AnalyzedItem], list[CarveOutOpportunity]]:
        """Analyze multiple items and extract carve-out opportunities."""
        total = len(items)

        if total == 0:
            return [], []

        if self.max_workers <= 1:
            analyzed_items: list[AnalyzedItem] = []
            carve_outs: list[CarveOutOpportunity] = []
            for i, item in enumerate(items):
                item_context = context_builder(item) if context_builder else None
                analyzed = self.analyze_item(item, item_context=item_context)
                analyzed_items.append(analyzed)

                if analyzed.carve_out_potential in (CarveOutPotential.HIGH, CarveOutPotential.MEDIUM):
                    carve_out = self._extract_carve_out(analyzed)
                    if carve_out:
                        carve_outs.append(carve_out)

                if on_progress:
                    on_progress(i + 1, total)

            return analyzed_items, carve_outs

        results: list[AnalyzedItem | None] = [None] * total
        completed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {}
            for idx, item in enumerate(items):
                item_context = context_builder(item) if context_builder else None
                future = executor.submit(self.analyze_item, item, item_context)
                future_map[future] = idx

            for future in as_completed(future_map):
                idx = future_map[future]
                results[idx] = future.result()
                completed += 1
                if on_progress:
                    on_progress(completed, total)

        analyzed_items = [item for item in results if item is not None]
        carve_outs: list[CarveOutOpportunity] = []
        for analyzed in analyzed_items:
            if analyzed.carve_out_potential in (CarveOutPotential.HIGH, CarveOutPotential.MEDIUM):
                carve_out = self._extract_carve_out(analyzed)
                if carve_out:
                    carve_outs.append(carve_out)

        return analyzed_items, carve_outs

    def _build_prompt(self, item: TriagedItem, item_context: str | None = None) -> str:
        """Build the full prompt for analysis."""
        system = ANALYSIS_SYSTEM_PROMPT.format(portfolio_context=self.portfolio_context)
        if item_context:
            system = f"{system}\n\n## Item-Specific Context\n{item_context}"
        full_text = item.raw_item.full_text or ""
        if full_text:
            full_text = full_text[:4000]
        else:
            full_text = "Not available."
        user = ANALYSIS_USER_PROMPT.format(
            title=item.raw_item.title,
            source=item.raw_item.source,
            date=item.raw_item.published_date.strftime("%Y-%m-%d") if item.raw_item.published_date else "Unknown",
            url=item.raw_item.source_url,
            summary=item.raw_item.summary,
            full_text=full_text,
            category=item.category.value,
            deal_type=item.deal_type.value,
            portfolio_company=item.related_portfolio_company or "None",
            competitors=", ".join(item.related_competitors) if item.related_competitors else "None",
            triage_reason=item.triage_reason,
        )
        return f"{system}\n\n{user}"

    def _get_client(self):
        client = getattr(self._thread_local, "client", None)
        if client is None:
            client = genai.GenerativeModel(self.model)
            self._thread_local.client = client
        return client

    def _parse_response(self, response_text: str) -> dict:
        """Parse JSON from LLM response."""
        text = response_text.strip()

        # Handle markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass

            logger.warning(f"Failed to parse analysis response: {e}")
            logger.debug(f"Response was: {response_text[:500]}")
            return {}

    def _build_analyzed_item(self, item: TriagedItem, result: dict) -> AnalyzedItem:
        """Build AnalyzedItem from parsed response."""
        return AnalyzedItem(
            triaged_item=item,
            why_it_matters=_coerce_text(result.get("why_it_matters")) or "Analysis unavailable.",
            strategic_implications=_coerce_text(result.get("strategic_implications")) or "",
            impact_on_silvertree=_coerce_text(result.get("impact_on_silvertree")) or "",
            competitive_threat_level=_coerce_threat_level(result.get("competitive_threat_level")),
            affected_portfolio_companies=_coerce_list(result.get("affected_portfolio_companies")),
            carve_out_potential=_coerce_carve_out(result.get("carve_out_potential")),
            carve_out_rationale=_coerce_text(result.get("carve_out_rationale")),
            carve_out_target_units=_coerce_list(result.get("carve_out_target_units")),
            key_entities=_coerce_dict(result.get("key_entities")),
            signal_score=_coerce_signal_score(result.get("signal_score", 50)),
            evidence=_coerce_list(result.get("evidence")),
        )

    def _build_default_analyzed_item(self, item: TriagedItem) -> AnalyzedItem:
        """Build default AnalyzedItem when analysis fails."""
        return AnalyzedItem(
            triaged_item=item,
            why_it_matters="Analysis failed - manual review recommended.",
            strategic_implications="",
            impact_on_silvertree="",
            competitive_threat_level=None,
            affected_portfolio_companies=[],
            carve_out_potential=CarveOutPotential.NOT_APPLICABLE,
            carve_out_rationale=None,
            carve_out_target_units=[],
            key_entities={},
            signal_score=0,
            evidence=[],
        )

    def _extract_carve_out(self, analyzed: AnalyzedItem) -> CarveOutOpportunity | None:
        """Extract carve-out opportunity from analyzed item."""
        if not analyzed.carve_out_target_units:
            return None

        # Determine target company from key entities
        target = None
        for entity, role in analyzed.key_entities.items():
            if role.lower() == "target":
                target = entity
                break

        if not target:
            target = _guess_target_from_title(analyzed.triaged_item.raw_item.title)

        if not target:
            target = analyzed.triaged_item.raw_item.title.split()[0]  # Final fallback

        return CarveOutOpportunity(
            source_item=analyzed,
            source_items=[analyzed],
            target_company=target,
            potential_units=analyzed.carve_out_target_units,
            strategic_fit_rationale=analyzed.carve_out_rationale or "",
            recommended_action="Monitor for potential acquisition opportunity",
            priority="high" if analyzed.carve_out_potential == CarveOutPotential.HIGH else "medium",
        )


def _guess_target_from_title(title: str) -> str | None:
    patterns = [
        r"acquires\s+(?P<target>.+)",
        r"acquired\s+(?P<target>.+)",
        r"to acquire\s+(?P<target>.+)",
        r"acquisition of\s+(?P<target>.+)",
        r"merges with\s+(?P<target>.+)",
        r"buying\s+(?P<target>.+)",
        r"buys\s+(?P<target>.+)",
        r"to buy\s+(?P<target>.+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, title, flags=re.IGNORECASE)
        if not match:
            continue
        target = match.group("target")
        target = re.split(r"\s+for\s+|\s+from\s+|\s+in\s+|\s+at\s+", target, maxsplit=1)[0]
        target = target.strip(" -:")
        if target:
            return target

    return None


def _coerce_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value)


def _coerce_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if "," in text:
            return [part.strip() for part in text.split(",") if part.strip()]
        return [text]
    return [str(value)]


def _coerce_dict(value) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key): str(val) for key, val in value.items() if str(key).strip()}
    return {}


def _coerce_threat_level(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"high", "medium", "low"}:
            return normalized
    return None


def _coerce_carve_out(value) -> CarveOutPotential:
    if isinstance(value, CarveOutPotential):
        return value
    if value is None:
        return CarveOutPotential.NOT_APPLICABLE
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return CarveOutPotential.NOT_APPLICABLE
        if normalized in {"not_applicable", "not applicable", "na", "n/a"}:
            normalized = "n/a"
        try:
            return CarveOutPotential(normalized)
        except ValueError:
            return CarveOutPotential.NOT_APPLICABLE
    return CarveOutPotential.NOT_APPLICABLE


def _coerce_signal_score(value, default: int = 50) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(100, score))


class RateLimiter:
    """Thread-safe rate limiter for sync LLM calls."""

    def __init__(self, requests_per_minute: int) -> None:
        self.min_interval = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self._lock = threading.Lock()
        self._last_request = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_request = time.monotonic()
