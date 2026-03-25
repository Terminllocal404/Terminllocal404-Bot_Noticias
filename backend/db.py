"""MySQL access layer for Cyber Intelligence Platform."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any, Iterable

import mysql.connector
from mysql.connector import Error, MySQLConnection


class Database:
    def __init__(self) -> None:
        self.config = {
            "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
            "port": int(os.getenv("MYSQL_PORT", "3306")),
            "user": os.getenv("MYSQL_USER", "cyberbot_user"),
            "password": os.getenv("MYSQL_PASSWORD", "change_this_password"),
            "database": os.getenv("MYSQL_DATABASE", "cyberbot"),
            "autocommit": False,
            "connection_timeout": 10,
        }
        self.conn: MySQLConnection | None = None
        self._ensure_connection()
        self.init_schema()

    def _ensure_connection(self) -> None:
        if self.conn and self.conn.is_connected():
            return
        for attempt in range(1, 4):
            try:
                self.conn = mysql.connector.connect(**self.config)
                return
            except Error:
                if attempt == 3:
                    raise
                time.sleep(2)

    @contextmanager
    def cursor(self):
        self._ensure_connection()
        if self.conn is None:
            raise RuntimeError("No MySQL connection")
        cur = self.conn.cursor(dictionary=True)
        try:
            yield cur
            self.conn.commit()
        except Error:
            self.conn.rollback()
            self.conn = None
            raise
        finally:
            cur.close()

    def init_schema(self) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS news (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    title TEXT NOT NULL,
                    link TEXT NOT NULL,
                    source VARCHAR(255) NOT NULL,
                    category VARCHAR(32) NOT NULL,
                    severity VARCHAR(16) NOT NULL,
                    summary TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uniq_news_link (link(255))
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS cves (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    cve_id VARCHAR(64) NOT NULL,
                    summary TEXT,
                    severity VARCHAR(16) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uniq_cve_id (cve_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

    def upsert_news(self, title: str, link: str, source: str, category: str, severity: str, summary: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news (title, link, source, category, severity, summary)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title = VALUES(title),
                    source = VALUES(source),
                    category = VALUES(category),
                    severity = VALUES(severity),
                    summary = VALUES(summary)
                """,
                (title, link, source, category, severity, summary),
            )

    def upsert_cve(self, cve_id: str, summary: str, severity: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cves (cve_id, summary, severity)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    summary = VALUES(summary),
                    severity = VALUES(severity)
                """,
                (cve_id, summary, severity),
            )

    def get_news(self, category: str | None = None, severity: str | None = None, search: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM news WHERE 1=1"
        params: list[Any] = []
        if category:
            query += " AND category = %s"
            params.append(category)
        if severity:
            query += " AND severity = %s"
            params.append(severity.upper())
        if search:
            query += " AND (title LIKE %s OR summary LIKE %s OR source LIKE %s)"
            term = f"%{search}%"
            params.extend([term, term, term])
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        with self.cursor() as cur:
            cur.execute(query, tuple(params))
            return list(cur.fetchall())

    def get_cves(self, severity: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM cves WHERE 1=1"
        params: list[Any] = []
        if severity:
            query += " AND severity = %s"
            params.append(severity.upper())
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        with self.cursor() as cur:
            cur.execute(query, tuple(params))
            return list(cur.fetchall())

    def get_alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute(
                "SELECT * FROM news WHERE severity IN ('HIGH','CRITICAL') ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            return list(cur.fetchall())

    def get_trends(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT title, category, severity, created_at
                FROM news
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return list(cur.fetchall())


def aggregate_severity_counts(items: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for item in items:
        level = str(item.get("severity", "LOW")).upper()
        if level in counts:
            counts[level] += 1
    return counts
