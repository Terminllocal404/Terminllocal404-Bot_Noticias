"""RSS feed ingestion and filtering logic."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List

import feedparser

from config import CATEGORY_KEYWORDS, CRITICAL_KEYWORDS, DEFAULT_KEYWORDS, RSS_FEEDS

LOGGER = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    link: str
    description: str
    source: str
    matched_keywords: List[str]
    score: int
    critical: bool


def _text_blob(entry: dict) -> str:
    title = entry.get("title", "")
    summary = entry.get("summary", "")
    tags = " ".join(tag.get("term", "") for tag in entry.get("tags", []))
    return f"{title} {summary} {tags}".lower()


def _score_item(text: str, category: str | None = None) -> tuple[list[str], int, bool]:
    matched = [kw for kw in DEFAULT_KEYWORDS if kw in text]
    score = len(matched)

    if category and category in CATEGORY_KEYWORDS:
        for kw in CATEGORY_KEYWORDS[category]:
            if kw in text and kw not in matched:
                matched.append(kw)
                score += 2

    critical = any(kw in text for kw in CRITICAL_KEYWORDS)
    if critical:
        score += 4
    return matched, score, critical


def fetch_news(category: str | None = None, limit: int = 10) -> List[NewsItem]:
    items: List[NewsItem] = []
    seen_links: set[str] = set()

    for feed_url in RSS_FEEDS:
        parsed = feedparser.parse(feed_url)
        if parsed.bozo:
            LOGGER.warning("Unable to parse feed %s: %s", feed_url, parsed.bozo_exception)
            continue

        source = parsed.feed.get("title", feed_url)
        for entry in parsed.entries:
            link = entry.get("link", "")
            if not link or link in seen_links:
                continue

            text = _text_blob(entry)
            matched, score, critical = _score_item(text, category)
            if not matched:
                continue

            if category and category in CATEGORY_KEYWORDS:
                if not any(kw in text for kw in CATEGORY_KEYWORDS[category]):
                    continue

            seen_links.add(link)
            items.append(
                NewsItem(
                    title=entry.get("title", "Untitled"),
                    link=link,
                    description=entry.get("summary", ""),
                    source=source,
                    matched_keywords=matched,
                    score=score,
                    critical=critical,
                )
            )

    items.sort(key=lambda item: (item.critical, item.score), reverse=True)
    return items[:limit]


def fetch_critical_alerts(limit: int = 8) -> List[NewsItem]:
    alerts = [item for item in fetch_news(category="security", limit=50) if item.critical]
    return alerts[:limit]


def extract_trend_keywords(items: Iterable[NewsItem]) -> Dict[str, int]:
    trend_counts: Dict[str, int] = {}
    for item in items:
        for kw in item.matched_keywords:
            trend_counts[kw] = trend_counts.get(kw, 0) + 1
    return trend_counts
