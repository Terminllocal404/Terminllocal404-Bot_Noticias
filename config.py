"""Configuration and constants for Cyber Intelligence Bot."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Settings:
    discord_token: str
    openai_api_key: str
    post_channel_id: int
    post_interval_minutes: int
    openai_model: str
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str


RSS_FEEDS: List[str] = [
    "https://www.bleepingcomputer.com/feed/",
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.phoronix.com/rss.php",
]

DEFAULT_KEYWORDS: List[str] = [
    "vulnerability",
    "exploit",
    "zero-day",
    "breach",
    "hack",
    "security",
    "linux",
    "windows",
]

CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "linux": ["linux", "kernel", "ubuntu", "debian", "red hat", "rhel", "fedora", "centos"],
    "windows": ["windows", "microsoft", "patch tuesday", "active directory", "defender"],
    "security": ["security", "vulnerability", "exploit", "zero-day", "breach", "ransomware", "malware"],
}

CRITICAL_KEYWORDS: List[str] = [
    "critical",
    "actively exploited",
    "remote code execution",
    "rce",
    "zero-day",
    "wormable",
    "privilege escalation",
    "breach",
]


def _require_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_settings() -> Settings:
    return Settings(
        discord_token=_require_env("DISCORD_BOT_TOKEN"),
        openai_api_key=_require_env("OPENAI_API_KEY"),
        post_channel_id=int(_require_env("DISCORD_POST_CHANNEL_ID")),
        post_interval_minutes=int(os.getenv("POST_INTERVAL_MINUTES", "30")),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        mysql_host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
        mysql_user=_require_env("MYSQL_USER"),
        mysql_password=_require_env("MYSQL_PASSWORD"),
        mysql_database=os.getenv("MYSQL_DATABASE", "cyberbot"),
    )
