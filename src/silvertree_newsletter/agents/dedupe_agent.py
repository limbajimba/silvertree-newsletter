"""LLM-assisted deduplication for collected news items."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from google import genai

from silvertree_newsletter.workflow.state import RawNewsItem

logger = logging.getLogger(__name__)


DEDUPE_SYSTEM_PROMPT = """You are deduplicating news items for a private equity newsletter.

Pick the single best canonical item when multiple items describe the same event.
Prefer: primary sources over aggregated search results, reputable outlets, clearer titles, and fuller summaries.
Ignore tracking params in URLs (utm_*, ref, source).

Respond with JSON only:
{
  "keep_id": "id to keep",
  "discard_ids": ["id1", "id2"],
  "reason": "brief rationale"
}
"""


_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "in", "on", "of", "by", "with",
    "from", "at", "as", "is", "are", "be", "will",
}


@dataclass
class DedupeAgent:
    """Deduplicate near-identical news items."""

    api_key: str
    model: str
    similarity_threshold: float = 0.9

    def __post_init__(self) -> None:
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None

    def dedupe_items(self, items: list[RawNewsItem]) -> tuple[list[RawNewsItem], dict]:
        """Return deduped items and stats."""
        if not items:
            return [], {"original": 0, "deduped": 0, "removed": 0}

        groups = self._group_duplicates(items)
        kept: list[RawNewsItem] = []
        removed = 0

        for group in groups:
            if len(group) == 1:
                kept.append(group[0])
                continue

            keep_id = self._select_canonical(group)
            selected = next((item for item in group if item.id == keep_id), None)
            if not selected:
                selected = self._fallback_select(group)

            kept.append(selected)
            removed += max(0, len(group) - 1)

        return kept, {"original": len(items), "deduped": len(kept), "removed": removed}

    def _group_duplicates(self, items: list[RawNewsItem]) -> list[list[RawNewsItem]]:
        """Group items that appear to be duplicates."""
        by_url: dict[str, list[RawNewsItem]] = {}
        for item in items:
            key = _canonical_url(item.source_url)
            by_url.setdefault(key, []).append(item)

        remaining: list[RawNewsItem] = []
        groups: list[list[RawNewsItem]] = []

        for group in by_url.values():
            if len(group) > 1:
                groups.append(group)
            else:
                remaining.append(group[0])

        used: set[str] = set()
        for idx, item in enumerate(remaining):
            if item.id in used:
                continue
            group = [item]
            used.add(item.id)

            for other in remaining[idx + 1:]:
                if other.id in used:
                    continue
                if _title_similarity(item.title, other.title) >= self.similarity_threshold:
                    group.append(other)
                    used.add(other.id)

            groups.append(group)

        return groups

    def _select_canonical(self, group: list[RawNewsItem]) -> str | None:
        payload = [
            {
                "id": item.id,
                "title": item.title,
                "source": item.source,
                "url": item.source_url,
                "published_date": item.published_date.isoformat() if item.published_date else None,
                "summary": item.summary[:600],
            }
            for item in group
        ]

        prompt = f"{DEDUPE_SYSTEM_PROMPT}\n\nItems:\n{json.dumps(payload, indent=2)}"

        if not self.client:
            return None

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            result = _extract_json(response.text)
            keep_id = result.get("keep_id")
            if keep_id:
                return keep_id
        except Exception as exc:
            logger.warning(f"Dedupe LLM failed: {exc}")

        return None

    def _fallback_select(self, group: Iterable[RawNewsItem]) -> RawNewsItem:
        def score(item: RawNewsItem) -> tuple[int, int, int, datetime | None]:
            date_score = 1 if item.published_date else 0
            summary_score = len(item.summary or "")
            source_score = 0 if item.source.startswith("perplexity") else 1
            return (source_score, date_score, summary_score, item.published_date)

        return max(group, key=score)


def _title_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    norm_a = _normalize_title(a)
    norm_b = _normalize_title(b)
    if not norm_a or not norm_b:
        return 0.0
    return SequenceMatcher(None, norm_a, norm_b).ratio()


def _normalize_title(title: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", title.lower())
    tokens = [tok for tok in text.split() if tok and tok not in _STOPWORDS]
    return " ".join(tokens)


def _canonical_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    query = parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [
        (key, value)
        for key, value in query
        if not key.lower().startswith("utm_") and key.lower() not in {"ref", "source"}
    ]
    new_query = urlencode(filtered, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _extract_json(text: str | None) -> dict:
    if not text:
        return {}

    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    return {}
