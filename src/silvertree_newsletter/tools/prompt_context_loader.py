"""Load and summarize prompt context guidance for LLM prompts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from silvertree_newsletter.models.schemas import CompanyProfile


def load_prompt_context(path: str | Path) -> dict | None:
    """Load prompt context JSON if present."""
    prompt_path = Path(path)
    if not prompt_path.exists():
        return None
    return json.loads(prompt_path.read_text(encoding="utf-8"))


def extract_relevance_thresholds(prompt_context: dict) -> dict[str, int]:
    """Extract relevance thresholds by category."""
    thresholds: dict[str, int] = {}
    guidelines = prompt_context.get("global_guidelines", {})
    defaults = guidelines.get("default_relevance_thresholds", {}) or {}

    portfolio = _normalize_score(defaults.get("portfolio_company_item_keep_if_score_gte"))
    competitor = _normalize_score(defaults.get("competitor_item_keep_if_score_gte"))
    major_deal = _normalize_score(defaults.get("major_deal_item_keep_if_score_gte"))
    industry = _normalize_score(defaults.get("industry_item_keep_if_score_gte"))

    if portfolio is not None:
        thresholds["portfolio"] = portfolio
    if competitor is not None:
        thresholds["competitor"] = competitor
    if major_deal is not None:
        thresholds["major_deal"] = major_deal
    if industry is not None:
        thresholds["industry"] = industry
    elif major_deal is not None:
        thresholds.setdefault("industry", major_deal)

    return thresholds


def build_item_context_for_triage(
    title: str,
    summary: str,
    prompt_context: dict,
    companies: list[CompanyProfile],
) -> str:
    """Build per-item context for triage."""
    text = _normalize_text(f"{title} {summary}")
    portfolio_entries, competitor_map, sector_playbooks = _build_portfolio_index(prompt_context)

    matched: set[str] = set()
    for name, entry in portfolio_entries.items():
        if name in text:
            matched.add(entry.get("company_id"))

    for competitor, parent_company_id in competitor_map.items():
        if competitor in text:
            matched.add(parent_company_id)

    if not matched:
        company_lines = []
        for company in companies:
            sector = f" ({company.sector})" if company.sector else ""
            company_lines.append(f"{company.name}{sector}")
        return "Portfolio companies: " + "; ".join(company_lines)

    return _format_company_context(matched, portfolio_entries, sector_playbooks)


def build_item_context_for_analysis(
    portfolio_company: str | None,
    competitors: list[str],
    prompt_context: dict,
) -> str:
    """Build per-item context for analysis using triage entities."""
    portfolio_entries, competitor_map, sector_playbooks = _build_portfolio_index(prompt_context)
    matched: set[str] = set()

    if portfolio_company:
        key = portfolio_company.strip().lower()
        entry = portfolio_entries.get(key)
        if entry:
            matched.add(entry.get("company_id"))

    for competitor in competitors:
        key = competitor.strip().lower()
        parent_company_id = competitor_map.get(key)
        if parent_company_id:
            matched.add(parent_company_id)

    if not matched:
        return ""

    return _format_company_context(matched, portfolio_entries, sector_playbooks)


def build_prompt_context_summary(
    prompt_context: dict,
    companies: list[CompanyProfile],
) -> str:
    """Build a compact summary string for prompt context."""
    lines: list[str] = []

    global_guidelines = prompt_context.get("global_guidelines", {})
    primary_goal = global_guidelines.get("primary_goal")
    if primary_goal:
        lines.append("Primary goal:")
        lines.append(f"- {primary_goal}")

    ignore_sources = global_guidelines.get("ignore_sources_global") or []
    if ignore_sources:
        lines.append("\nIgnore sources (global):")
        lines.append("- " + "; ".join(ignore_sources))

    carveout = global_guidelines.get("carveout_screening_global_heuristics", {})
    positives = carveout.get("strong_positive_signals") or []
    if positives:
        lines.append("\nCarve-out positive signals (short list):")
        lines.append("- " + "; ".join(positives[:3]))

    improvements = prompt_context.get("llm_prompt_context_improvements", {})
    scoring = improvements.get("event_scoring_rubric", {})
    base_scores = scoring.get("base_score_by_event_type", {})
    adjustments = scoring.get("adjustments", {})
    if base_scores:
        lines.append("\nSignal score base (0-100):")
        base_pairs = [f"{key}={value}" for key, value in list(base_scores.items())[:8]]
        lines.append("- " + "; ".join(base_pairs))
    if adjustments:
        lines.append("\nSignal score adjustments:")
        adjust_pairs = [f"{key} {value}" for key, value in list(adjustments.items())[:6]]
        lines.append("- " + "; ".join(adjust_pairs))

    sector_playbooks = prompt_context.get("sector_playbooks", {})
    portfolio_context = prompt_context.get("portfolio_companies", [])
    by_company_id = {item.get("company_id"): item for item in portfolio_context if item.get("company_id")}

    for company in companies:
        context = by_company_id.get(company.company_id)
        if not context:
            continue

        lines.append(f"\nCompany: {company.name}")
        core_thesis = context.get("core_thesis")
        if core_thesis:
            lines.append(f"- Thesis: {core_thesis}")
        priority = context.get("current_strategic_priority")
        if priority:
            lines.append(f"- Priority: {priority}")

        competitors = context.get("must_monitor_competitors") or []
        if competitors:
            names = [entry.get("name") for entry in competitors if entry.get("name")]
            if names:
                lines.append("- Must-monitor competitors: " + ", ".join(names[:3]))

        sector_key = context.get("sector_cluster") or company.cluster_id
        playbook = sector_playbooks.get(sector_key or "")
        if playbook:
            high_signal = playbook.get("ranked_high_signal_events") or []
            low_signal = playbook.get("ranked_low_signal_events") or []
            if high_signal:
                events = [entry.get("event_type") for entry in high_signal if entry.get("event_type")]
                lines.append("- High-signal events: " + "; ".join(events[:2]))
            if low_signal:
                events = [entry.get("event_type") for entry in low_signal if entry.get("event_type")]
                lines.append("- Low-signal events: " + "; ".join(events[:1]))

    return "\n".join(lines).strip()


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower())


def _normalize_score(value) -> int | None:
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score <= 10:
        return int(score * 10)
    return int(score)


def _build_portfolio_index(prompt_context: dict) -> tuple[dict, dict, dict]:
    portfolio_context = prompt_context.get("portfolio_companies", [])
    sector_playbooks = prompt_context.get("sector_playbooks", {})
    by_name: dict[str, dict] = {}
    competitor_map: dict[str, str] = {}

    for entry in portfolio_context:
        name = entry.get("name", "")
        company_id = entry.get("company_id")
        if name and company_id:
            by_name[name.lower()] = entry

        for competitor in entry.get("must_monitor_competitors", []) or []:
            competitor_name = competitor.get("name")
            if competitor_name and company_id:
                competitor_map[competitor_name.lower()] = company_id

    return by_name, competitor_map, sector_playbooks


def _format_company_context(
    company_ids: set[str],
    portfolio_entries: dict,
    sector_playbooks: dict,
) -> str:
    lines: list[str] = []
    by_company_id = {entry.get("company_id"): entry for entry in portfolio_entries.values() if entry.get("company_id")}

    for company_id in company_ids:
        entry = by_company_id.get(company_id)
        if not entry:
            continue
        lines.append(f"Company: {entry.get('name')}")

        thesis = entry.get("core_thesis")
        if thesis:
            lines.append(f"- Thesis: {thesis}")
        priority = entry.get("current_strategic_priority")
        if priority:
            lines.append(f"- Priority: {priority}")

        competitors = entry.get("must_monitor_competitors") or []
        names = [c.get("name") for c in competitors if c.get("name")]
        if names:
            lines.append("- Must-monitor competitors: " + ", ".join(names[:3]))

        ignore = entry.get("ignore_sources") or []
        if ignore:
            lines.append("- Ignore sources: " + "; ".join(ignore[:2]))

        sector_key = entry.get("sector_cluster")
        playbook = sector_playbooks.get(sector_key or "")
        if playbook:
            high_signal = playbook.get("ranked_high_signal_events") or []
            low_signal = playbook.get("ranked_low_signal_events") or []
            if high_signal:
                events = [ev.get("event_type") for ev in high_signal if ev.get("event_type")]
                lines.append("- High-signal events: " + "; ".join(events[:2]))
            if low_signal:
                events = [ev.get("event_type") for ev in low_signal if ev.get("event_type")]
                lines.append("- Low-signal events: " + "; ".join(events[:1]))

    return "\n".join(lines).strip()
