"""Triage Agent - Fast categorization of news items.

This agent processes ALL collected news items quickly to determine:
1. Is it relevant to SilverTree?
2. What category? (portfolio, competitor, major_deal, industry)
3. What type of news? (M&A, fundraising, product, personnel, etc.)
4. Which portfolio company/competitor is it related to?

Speed is critical - this runs on 100+ items.
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
    RawNewsItem,
    TriagedItem,
    ItemCategory,
    DealType,
    RelevanceLevel,
)

logger = logging.getLogger(__name__)


TRIAGE_SYSTEM_PROMPT = """You are a news triage analyst for SilverTree Equity, a private equity firm.

Your job is to quickly categorize news items to determine if they are relevant to SilverTree's portfolio and investment interests.

## SilverTree Portfolio Context
{portfolio_context}

## Your Task
For each news item, determine:

1. **Is it relevant?** Does this news item matter to SilverTree?
   - Direct news about a portfolio company = RELEVANT
   - News about a competitor of a portfolio company = RELEVANT
   - Major M&A/fundraising deal in a relevant sector = RELEVANT
   - General industry news in portfolio sectors = MAYBE RELEVANT
   - Unrelated news = NOT RELEVANT

Hard filters (mark NOT RELEVANT):
- Job postings, careers pages, or hiring ads
- Generic listicles, directories, or "top tools" blog posts
- Vendor marketing pages with no new event
- Generic educational content or definitions
- Random ecommerce product pages or unrelated retail listings

2. **Category** (if relevant):
   - `portfolio` - Direct news about a SilverTree portfolio company
   - `competitor` - News about a competitor to a portfolio company
   - `major_deal` - M&A, fundraising, IPO, large partnership (even if not direct competitor)
   - `industry` - Broader industry news affecting portfolio sectors
   - `not_relevant` - Not relevant to SilverTree

3. **Deal Type** (what kind of news):
   - `ma_acquisition` - Company acquiring another
   - `ma_merger` - Two companies merging
   - `divestiture` - Company selling a division/unit
   - `fundraising` - Funding round, investment
   - `ipo` - Going public
   - `partnership` - Strategic partnership, alliance
   - `product_launch` - New product or feature
   - `personnel_change` - Executive appointment, departure
   - `strategic_update` - Strategy change, restructuring
   - `not_a_deal` - General news, not transaction-related

4. **Related Entities**:
   - Which portfolio company is affected? (exact name from list)
   - Which competitors are mentioned?
   - What sector?

5. **Confidence** (0-100): How confident are you in this categorization?

## Output Format
Respond with ONLY a JSON object:
```json
{{
    "is_relevant": true/false,
    "category": "portfolio" | "competitor" | "major_deal" | "industry" | "not_relevant",
    "deal_type": "ma_acquisition" | "ma_merger" | "divestiture" | "fundraising" | "ipo" | "partnership" | "product_launch" | "personnel_change" | "strategic_update" | "not_a_deal",
    "relevance_level": "high" | "medium" | "low",
    "confidence": 0-100,
    "related_portfolio_company": "Company Name" or null,
    "related_competitors": ["Competitor1", "Competitor2"] or [],
    "related_sector": "Sector name" or null,
    "triage_reason": "One sentence explaining why this is/isn't relevant"
}}
```

Be decisive. When in doubt about relevance, lean toward including it (we filter later).
For M&A deals, always categorize as `major_deal` even if companies aren't direct competitors.
"""


TRIAGE_USER_PROMPT = """Categorize this news item:

**Title:** {title}
**Source:** {source}
**Date:** {date}
**URL:** {url}
**Summary:** {summary}

Respond with JSON only."""


@dataclass
class TriageAgent:
    """Fast categorization agent for news items."""

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

    def triage_item(self, item: RawNewsItem, item_context: str | None = None) -> TriagedItem:
        """Triage a single news item."""
        prompt = self._build_prompt(item, item_context)

        try:
            if self._rate_limiter:
                self._rate_limiter.wait()
            response = self._get_client().generate_content(prompt)
            result = self._parse_response(response.text)
            return self._build_triaged_item(item, result)
        except Exception as e:
            logger.error(f"Triage failed for {item.id}: {e}")
            return self._build_default_triaged_item(item)

    def triage_batch(
        self,
        items: list[RawNewsItem],
        on_progress: callable | None = None,
        context_builder: callable | None = None,
    ) -> list[TriagedItem]:
        """Triage multiple items."""
        total = len(items)

        if total == 0:
            return []

        if self.max_workers <= 1:
            results: list[TriagedItem] = []
            for i, item in enumerate(items):
                item_context = context_builder(item) if context_builder else None
                triaged = self.triage_item(item, item_context=item_context)
                results.append(triaged)

                if on_progress:
                    on_progress(i + 1, total)
            return results

        results: list[TriagedItem | None] = [None] * total
        completed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {}
            for idx, item in enumerate(items):
                item_context = context_builder(item) if context_builder else None
                future = executor.submit(self.triage_item, item, item_context)
                future_map[future] = idx

            for future in as_completed(future_map):
                idx = future_map[future]
                results[idx] = future.result()
                completed += 1
                if on_progress:
                    on_progress(completed, total)

        return [item for item in results if item is not None]

    def _build_prompt(self, item: RawNewsItem, item_context: str | None = None) -> str:
        """Build the full prompt for triage."""
        system = TRIAGE_SYSTEM_PROMPT.format(portfolio_context=self.portfolio_context)
        if item_context:
            system = f"{system}\n\n## Item-Specific Context\n{item_context}"
        user = TRIAGE_USER_PROMPT.format(
            title=item.title,
            source=item.source,
            date=item.published_date.strftime("%Y-%m-%d") if item.published_date else "Unknown",
            url=item.source_url,
            summary=item.summary[:500],  # Truncate for speed
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
            # Remove first and last lines (```json and ```)
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

            logger.warning(f"Failed to parse triage response: {e}")
            logger.debug(f"Response was: {response_text[:500]}")
            return {}

    def _build_triaged_item(self, item: RawNewsItem, result: dict) -> TriagedItem:
        """Build TriagedItem from parsed response."""
        return TriagedItem(
            raw_item=item,
            is_relevant=_coerce_bool(result.get("is_relevant", False)),
            category=_coerce_enum(ItemCategory, result.get("category"), ItemCategory.NOT_RELEVANT),
            deal_type=_coerce_enum(DealType, result.get("deal_type"), DealType.NOT_A_DEAL),
            relevance_level=_coerce_enum(RelevanceLevel, result.get("relevance_level"), RelevanceLevel.LOW),
            confidence=_coerce_confidence(result.get("confidence", 50)),
            related_portfolio_company=_coerce_text(result.get("related_portfolio_company")),
            related_competitors=_coerce_list(result.get("related_competitors")),
            related_sector=_coerce_text(result.get("related_sector")),
            triage_reason=_coerce_text(result.get("triage_reason")) or "",
        )

    def _build_default_triaged_item(self, item: RawNewsItem) -> TriagedItem:
        """Build default TriagedItem when triage fails."""
        return TriagedItem(
            raw_item=item,
            is_relevant=False,
            category=ItemCategory.NOT_RELEVANT,
            deal_type=DealType.NOT_A_DEAL,
            relevance_level=RelevanceLevel.LOW,
            confidence=0,
            related_portfolio_company=None,
            related_competitors=[],
            related_sector=None,
            triage_reason="Triage failed - marked as not relevant",
        )


def _coerce_enum(enum_cls, value, default):
    if isinstance(value, enum_cls):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        value = normalized
    try:
        return enum_cls(value)
    except ValueError:
        return default


def _coerce_confidence(value, default: int = 50) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(100, score))


def _coerce_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "yes", "1"):
            return True
        if normalized in ("false", "no", "0"):
            return False
    if value is None:
        return default
    return bool(value)


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


def _coerce_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value)


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
