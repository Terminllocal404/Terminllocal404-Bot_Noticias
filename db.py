"""SQLite storage for deduplication, CVE tracking, and trend analytics."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, Iterable, List, Tuple


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS posted_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    link TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT,
                    category TEXT,
                    posted_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS shown_cves (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cve_id TEXT UNIQUE NOT NULL,
                    severity TEXT,
                    shown_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS keyword_hits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(keyword)
                )
                """
            )
            conn.commit()

    def has_posted_link(self, link: str) -> bool:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM posted_news WHERE link = ? LIMIT 1", (link,))
            return cursor.fetchone() is not None

    def mark_link_posted(self, link: str, title: str, source: str, category: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO posted_news(link, title, source, category, posted_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (link, title, source, category, now),
            )
            conn.commit()

    def has_shown_cve(self, cve_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM shown_cves WHERE cve_id = ? LIMIT 1", (cve_id,))
            return cursor.fetchone() is not None

    def mark_cve_shown(self, cve_id: str, severity: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO shown_cves(cve_id, severity, shown_at)
                VALUES (?, ?, ?)
                """,
                (cve_id, severity, now),
            )
            conn.commit()

    def update_keyword_hits(self, keywords: Iterable[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.cursor()
            for keyword in keywords:
                cursor.execute(
                    """
                    INSERT INTO keyword_hits(keyword, hit_count, updated_at)
                    VALUES (?, 1, ?)
                    ON CONFLICT(keyword) DO UPDATE SET
                        hit_count = hit_count + 1,
                        updated_at = excluded.updated_at
                    """,
                    (keyword.lower(), now),
                )
            conn.commit()

    def top_trends(self, limit: int = 10) -> List[Tuple[str, int]]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT keyword, hit_count
                FROM keyword_hits
                ORDER BY hit_count DESC, keyword ASC
                LIMIT ?
                """,
                (limit,),
            )
            return cursor.fetchall()
