"""Carve-out research agent for deep-dive opportunity dossiers."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from google import genai

from silvertree_newsletter.workflow.state import CarveOutOpportunity

logger = logging.getLogger(__name__)


CARVE_OUT_RESEARCH_SYSTEM_PROMPT = """You are a senior private equity associate preparing a carve-out research dossier.

Use ONLY the provided sources and context. Do NOT invent facts or assume details not in the sources.
If something is unknown, state "unknown" or "not stated".

Provide clear, decision-useful analysis that ties back to SilverTree's carve-out playbooks.

Output JSON only with this schema:
{
  "deal_summary": "2-3 sentences",
  "deal_overview": "Concise paragraph describing the transaction and parties",
  "potential_assets": ["list of assets or units that could be carved out"],
  "separation_complexity": "low" | "medium" | "high" | "unknown",
  "separation_drivers": ["data", "people", "contracts", "infrastructure", "regulatory", "delivery", "commercial"],
  "estimated_separation_timeline_months": "string range or unknown",
  "strategic_fit": "1-2 paragraphs linking to SilverTree thesis",
  "what_silvertree_would_do": "one-line: bolt-on, platform add-on, or stand-alone carve-out",
  "risks": ["key risks or constraints"],
  "diligence_questions": ["specific diligence questions to validate feasibility"],
  "next_steps": ["recommended actions"],
  "confidence": "low" | "medium" | "high"
}
"""


CARVE_OUT_RESEARCH_USER_PROMPT = """Carve-out candidate context (JSON):
{candidate_json}

Sources (JSON):
{sources_json}

Return JSON only."""


@dataclass
class CarveOutResearchAgent:
    """Generate a detailed carve-out research dossier."""

    api_key: str
    model: str = "gemini-2.5-pro"
    requests_per_minute: int = 0
    max_sources: int = 20
    max_full_text_chars: int = 4000

    def __post_init__(self) -> None:
        self.client = genai.Client(api_key=self.api_key)
        self._rate_limiter = RateLimiter(self.requests_per_minute) if self.requests_per_minute else None

    def generate_report(
        self,
        carve_outs: list[CarveOutOpportunity],
        *,
        context_builder: callable | None = None,
        on_progress: callable | None = None,
    ) -> str:
        if not carve_outs:
            return ""

        entries: list[dict] = []
        total = len(carve_outs)

        for idx, carve_out in enumerate(carve_outs):
            context = context_builder(carve_out) if context_builder else ""
            prompt = self._build_prompt(carve_out, context)

            try:
                if self._rate_limiter:
                    self._rate_limiter.wait()
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                )
                result = self._parse_response(response.text)
                entry = _coerce_entry(result, carve_out)
            except Exception as exc:
                logger.error(f"Carve-out research failed for {carve_out.target_company}: {exc}")
                entry = _default_entry(carve_out)

            entries.append(entry)
            if on_progress:
                on_progress(idx + 1, total)

        return _render_markdown(entries, carve_outs)

    def _build_prompt(self, carve_out: CarveOutOpportunity, context: str) -> str:
        sources = []
        source_items = carve_out.source_items or [carve_out.source_item]
        for item in source_items[: self.max_sources]:
            raw = item.triaged_item.raw_item
            full_text = raw.full_text or ""
            if full_text and len(full_text) > self.max_full_text_chars:
                full_text = full_text[: self.max_full_text_chars]
            sources.append(
                {
                    "title": raw.title,
                    "source": raw.source,
                    "url": raw.source_url,
                    "published_date": raw.published_date.isoformat() if raw.published_date else None,
                    "summary": raw.summary,
                    "full_text": full_text or "Not available.",
                }
            )

        source_item = carve_out.source_item
        triaged = source_item.triaged_item
        candidate = {
            "target_company": carve_out.target_company,
            "priority": carve_out.priority,
            "potential_units": carve_out.potential_units,
            "strategic_fit_rationale": carve_out.strategic_fit_rationale,
            "recommended_action": carve_out.recommended_action,
            "deal_type": triaged.deal_type.value,
            "category": triaged.category.value,
            "portfolio_company": triaged.related_portfolio_company,
            "competitors": triaged.related_competitors,
            "impact_on_silvertree": source_item.impact_on_silvertree,
            "why_it_matters": source_item.why_it_matters,
            "strategic_implications": source_item.strategic_implications,
            "carve_out_rationale": source_item.carve_out_rationale,
            "signal_score": source_item.signal_score,
            "evidence": source_item.evidence,
            "key_entities": source_item.key_entities,
        }

        system = CARVE_OUT_RESEARCH_SYSTEM_PROMPT
        if context:
            system = f"{system}\n\nCarve-out playbook context:\n{context}"

        user = CARVE_OUT_RESEARCH_USER_PROMPT.format(
            candidate_json=json.dumps(candidate, indent=2, ensure_ascii=True),
            sources_json=json.dumps(sources, indent=2, ensure_ascii=True),
        )

        return f"{system}\n\n{user}"

    def _parse_response(self, response_text: str) -> dict:
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    return {}
        return {}


def _coerce_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
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


def _coerce_enum(value, allowed: set[str], fallback: str) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in allowed:
            return normalized
    return fallback


def _coerce_entry(result: dict, carve_out: CarveOutOpportunity) -> dict:
    return {
        "deal_summary": _coerce_text(result.get("deal_summary")) or carve_out.source_item.why_it_matters,
        "deal_overview": _coerce_text(result.get("deal_overview")),
        "potential_assets": _coerce_list(result.get("potential_assets")) or carve_out.potential_units,
        "separation_complexity": _coerce_enum(
            result.get("separation_complexity"), {"low", "medium", "high", "unknown"}, "unknown"
        ),
        "separation_drivers": _coerce_list(result.get("separation_drivers")),
        "estimated_separation_timeline_months": _coerce_text(
            result.get("estimated_separation_timeline_months")
        )
        or "unknown",
        "strategic_fit": _coerce_text(result.get("strategic_fit")) or carve_out.strategic_fit_rationale,
        "what_silvertree_would_do": _coerce_text(result.get("what_silvertree_would_do")),
        "risks": _coerce_list(result.get("risks")),
        "diligence_questions": _coerce_list(result.get("diligence_questions")),
        "next_steps": _coerce_list(result.get("next_steps")),
        "confidence": _coerce_enum(result.get("confidence"), {"low", "medium", "high"}, "medium"),
    }


def _default_entry(carve_out: CarveOutOpportunity) -> dict:
    source_item = carve_out.source_item
    return {
        "deal_summary": source_item.why_it_matters,
        "deal_overview": "",
        "potential_assets": carve_out.potential_units,
        "separation_complexity": "unknown",
        "separation_drivers": [],
        "estimated_separation_timeline_months": "unknown",
        "strategic_fit": carve_out.strategic_fit_rationale or source_item.why_it_matters,
        "what_silvertree_would_do": "",
        "risks": [],
        "diligence_questions": [],
        "next_steps": [],
        "confidence": "low",
    }


def _render_markdown(entries: list[dict], carve_outs: list[CarveOutOpportunity]) -> str:
    now = datetime.now(timezone.utc)
    lines: list[str] = []
    lines.append("# Carve-Out Research Dossier")
    lines.append("")
    lines.append(f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"Total opportunities: {len(entries)}")

    for entry, carve_out in zip(entries, carve_outs):
        source_item = carve_out.source_item
        raw = source_item.triaged_item.raw_item
        sources = carve_out.source_items or [source_item]

        lines.append("")
        lines.append(f"## {carve_out.target_company} ({carve_out.priority} priority)")
        lines.append(f"- Deal headline: {raw.title}")
        if raw.source_url:
            lines.append(f"- Primary source: {raw.source_url}")
        if carve_out.potential_units:
            lines.append(f"- Potential units: {', '.join(carve_out.potential_units)}")
        rationale = carve_out.strategic_fit_rationale or source_item.carve_out_rationale or ""
        if rationale:
            lines.append(f"- Initial rationale: {rationale}")

        lines.append("")
        lines.append("### Deal Summary")
        lines.append(entry.get("deal_summary", "") or "unknown")

        overview = entry.get("deal_overview", "")
        if overview:
            lines.append("")
            lines.append("### Deal Overview")
            lines.append(overview)

        lines.append("")
        lines.append("### Potential Carve-Out Assets")
        assets = entry.get("potential_assets", []) or []
        if assets:
            for asset in assets:
                lines.append(f"- {asset}")
        else:
            lines.append("- unknown")

        lines.append("")
        lines.append("### Separation Complexity")
        lines.append(f"- Rating: {entry.get('separation_complexity', 'unknown')}")
        drivers = entry.get("separation_drivers", []) or []
        if drivers:
            lines.append(f"- Drivers: {', '.join(drivers)}")
        timeline = entry.get("estimated_separation_timeline_months", "unknown")
        if timeline:
            lines.append(f"- Estimated timeline (months): {timeline}")

        strategic_fit = entry.get("strategic_fit", "")
        if strategic_fit:
            lines.append("")
            lines.append("### Strategic Fit")
            lines.append(strategic_fit)

        what_to_do = entry.get("what_silvertree_would_do", "")
        if what_to_do:
            lines.append("")
            lines.append("### What SilverTree Would Do")
            lines.append(what_to_do)

        risks = entry.get("risks", []) or []
        if risks:
            lines.append("")
            lines.append("### Risks and Constraints")
            for risk in risks:
                lines.append(f"- {risk}")

        questions = entry.get("diligence_questions", []) or []
        if questions:
            lines.append("")
            lines.append("### Diligence Questions")
            for question in questions:
                lines.append(f"- {question}")

        next_steps = entry.get("next_steps", []) or []
        if next_steps:
            lines.append("")
            lines.append("### Next Steps")
            for step in next_steps:
                lines.append(f"- {step}")

        lines.append("")
        lines.append("### Sources")
        for item in sources:
            item_raw = item.triaged_item.raw_item
            if item_raw.source_url:
                lines.append(f"- {item_raw.title} ({item_raw.source_url})")
            else:
                lines.append(f"- {item_raw.title}")

        confidence = entry.get("confidence", "")
        if confidence:
            lines.append("")
            lines.append(f"Confidence: {confidence}")

    return "\n".join(lines).strip()


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
