"""Data collection engine for RSS and public threat feeds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import feedparser
import requests

KEYWORDS = [
    "vulnerability",
    "exploit",
    "zero-day",
    "breach",
    "rce",
    "privilege escalation",
]

RSS_FEEDS = {
    "security": [
        "https://www.bleepingcomputer.com/feed/",
        "https://feeds.feedburner.com/TheHackersNews",
        "https://krebsonsecurity.com/feed/",
        "https://www.darkreading.com/rss.xml",
        "https://www.securityweek.com/feed/",
    ],
    "linux": [
        "https://www.phoronix.com/rss.php",
        "https://www.omgubuntu.co.uk/feed",
        "https://itsfoss.com/feed/",
    ],
    "windows": [
        "https://www.windowscentral.com/rss",
        "https://msrc.microsoft.com/update-guide/rss",
    ],
}

ABUSE_CH_URL = "https://urlhaus-api.abuse.ch/v1/urls/recent/"


@dataclass
class RawItem:
    title: str
    link: str
    description: str
    source: str
    category: str


def _text_blob(title: str, summary: str, tags: Iterable[str]) -> str:
    return f"{title} {summary} {' '.join(tags)}".lower()


def _matches_keywords(text: str) -> bool:
    return any(keyword in text for keyword in KEYWORDS)


def _detect_category(text: str, fallback: str) -> str:
    if "linux" in text or "ubuntu" in text or "kernel" in text:
        return "linux"
    if "windows" in text or "microsoft" in text:
        return "windows"
    if "malware" in text or "threat" in text or "phishing" in text:
        return "threat"
    return fallback


def fetch_rss_items() -> list[RawItem]:
    items: list[RawItem] = []
    seen: set[str] = set()

    for category, feeds in RSS_FEEDS.items():
        for url in feeds:
            parsed = feedparser.parse(url)
            source = parsed.feed.get("title", url)
            for entry in parsed.entries:
                link = entry.get("link", "")
                if not link or link in seen:
                    continue
                title = entry.get("title", "Untitled")
                summary = entry.get("summary", "")
                tags = [t.get("term", "") for t in entry.get("tags", [])]
                blob = _text_blob(title, summary, tags)
                if not _matches_keywords(blob):
                    continue

                seen.add(link)
                items.append(
                    RawItem(
                        title=title,
                        link=link,
                        description=summary,
                        source=source,
                        category=_detect_category(blob, category),
                    )
                )

    return items


def fetch_abusech_items() -> list[RawItem]:
    try:
        response = requests.post(ABUSE_CH_URL, timeout=20)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []

    items: list[RawItem] = []
    for entry in data.get("urls", [])[:25]:
        url = entry.get("url")
        threat = entry.get("threat", "malware")
        if not url:
            continue

        title = f"Abuse.ch URLhaus {threat} indicator"
        summary = f"Threat feed indicator observed: {url}"
        items.append(
            RawItem(
                title=title,
                link=url,
                description=summary,
                source="Abuse.ch URLhaus",
                category="threat",
            )
        )

    return items
