"""MySQL storage for deduplication, CVE tracking, and trend analytics."""

from __future__ import annotations

import time
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Generator, List, Tuple

import mysql.connector
from mysql.connector import Error, MySQLConnection


class Database:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
    ) -> None:
        self._config = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            "autocommit": False,
            "connection_timeout": 10,
        }
        self._conn: MySQLConnection | None = None
        self._ensure_connection()
        self._init_db()

    def _ensure_connection(self) -> None:
        if self._conn and self._conn.is_connected():
            return

        for attempt in range(1, 4):
            try:
                self._conn = mysql.connector.connect(**self._config)
                return
            except Error:
                if attempt == 3:
                    raise
                time.sleep(2)

    @contextmanager
    def _cursor(self, dictionary: bool = False):
        self._ensure_connection()
        if self._conn is None:
            raise RuntimeError("MySQL connection is not available")

        try:
            cursor = self._conn.cursor(dictionary=dictionary)
            yield cursor
            self._conn.commit()
        except Error:
            if self._conn:
                self._conn.rollback()
            self._conn = None
            raise
        finally:
            if 'cursor' in locals() and cursor:
                cursor.close()

    def close(self) -> None:
        if self._conn and self._conn.is_connected():
            self._conn.close()

    def _init_db(self) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS news (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    title TEXT NOT NULL,
                    link TEXT NOT NULL,
                    category VARCHAR(50) NOT NULL,
                    source VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uniq_link (link(255))
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS cves (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    cve_id VARCHAR(64) NOT NULL,
                    summary TEXT,
                    severity VARCHAR(16) NOT NULL,
                    cvss FLOAT NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uniq_cve_id (cve_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    message TEXT NOT NULL,
                    level VARCHAR(16) NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS keyword_hits (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    keyword VARCHAR(100) NOT NULL,
                    hit_count INT NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uniq_keyword (keyword)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

    def has_posted_link(self, link: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute("SELECT 1 FROM news WHERE link = %s LIMIT 1", (link,))
            return cursor.fetchone() is not None

    def mark_link_posted(self, title: str, link: str, category: str, source: str) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO news (title, link, category, source)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE title = VALUES(title), category = VALUES(category), source = VALUES(source)
                """,
                (title, link, category, source),
            )

    def has_cve(self, cve_id: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute("SELECT 1 FROM cves WHERE cve_id = %s LIMIT 1", (cve_id,))
            return cursor.fetchone() is not None

    def store_cve(self, cve_id: str, summary: str, severity: str, cvss: float) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO cves (cve_id, summary, severity, cvss)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    summary = VALUES(summary),
                    severity = VALUES(severity),
                    cvss = VALUES(cvss)
                """,
                (cve_id, summary, severity, cvss),
            )

    def update_keyword_hits(self, keywords: Iterable[str]) -> None:
        with self._cursor() as cursor:
            for keyword in keywords:
                cursor.execute(
                    """
                    INSERT INTO keyword_hits (keyword, hit_count)
                    VALUES (%s, 1)
                    ON DUPLICATE KEY UPDATE hit_count = hit_count + 1
                    """,
                    (keyword.lower(),),
                )

    def top_trends(self, limit: int = 10) -> List[Tuple[str, int]]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT keyword, hit_count
                FROM keyword_hits
                ORDER BY hit_count DESC, keyword ASC
                LIMIT %s
                """,
                (limit,),
            )
            return list(cursor.fetchall())

    def log(self, message: str, level: str = "INFO") -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO logs (message, level) VALUES (%s, %s)",
                (message, level.upper()),
            )
