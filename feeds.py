"""Aggregation engine for RSS ingestion, normalization, and filtering."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List

import feedparser

from config import CATEGORY_KEYWORDS, DEFAULT_KEYWORDS, RSS_FEEDS
from scoring import compute_severity_score

LOGGER = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    link: str
    description: str
    source: str
    category: str
    matched_keywords: List[str]
    severity_score: int
    severity_level: str


def _text_blob(entry: dict) -> str:
    title = entry.get("title", "")
    summary = entry.get("summary", "")
    tags = " ".join(tag.get("term", "") for tag in entry.get("tags", []))
    return f"{title} {summary} {tags}".lower()


def _classify_category(text: str, feed_category: str) -> str:
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "threat" if feed_category == "security" else feed_category


def _matches_filter(text: str, category: str | None) -> tuple[bool, list[str]]:
    matched = [keyword for keyword in DEFAULT_KEYWORDS if keyword in text]

    if category and category in CATEGORY_KEYWORDS:
        matched += [k for k in CATEGORY_KEYWORDS[category] if k in text and k not in matched]

    return bool(matched), matched


def fetch_news(category: str | None = None, limit: int = 15) -> List[NewsItem]:
    items: List[NewsItem] = []
    seen_links: set[str] = set()

    feed_scope = RSS_FEEDS.keys() if category is None else [category]
    for feed_category in feed_scope:
        for feed_url in RSS_FEEDS.get(feed_category, []):
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
                ok, matched = _matches_filter(text, category)
                if not ok:
                    continue

                detected_category = _classify_category(text, feed_category)
                if category and detected_category != category:
                    continue

                severity = compute_severity_score(text)
                seen_links.add(link)
                items.append(
                    NewsItem(
                        title=entry.get("title", "Untitled"),
                        link=link,
                        description=entry.get("summary", ""),
                        source=source,
                        category=detected_category,
                        matched_keywords=matched,
                        severity_score=severity.score,
                        severity_level=severity.level,
                    )
                )

    items.sort(key=lambda item: (item.severity_score, len(item.matched_keywords)), reverse=True)
    return items[:limit]


def fetch_critical_alerts(limit: int = 8) -> List[NewsItem]:
    return [item for item in fetch_news(category=None, limit=60) if item.severity_level in {"HIGH", "CRITICAL"}][:limit]


def extract_trend_keywords(items: Iterable[NewsItem]) -> Dict[str, int]:
    trends: Dict[str, int] = {}
    for item in items:
        for keyword in item.matched_keywords:
            trends[keyword] = trends.get(keyword, 0) + 1
    return trends
