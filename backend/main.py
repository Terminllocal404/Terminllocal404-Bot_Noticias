"""Collector worker + API launcher entrypoint."""

from __future__ import annotations

import asyncio
import os

import uvicorn

from ai import AISummarizer
from cve import fetch_latest_cves
from db import Database
from feeds import fetch_abusech_items, fetch_rss_items

COLLECT_INTERVAL_SECONDS = int(os.getenv("COLLECT_INTERVAL_SECONDS", "1800"))


async def run_collector_loop() -> None:
    db = Database()
    ai = AISummarizer()

    while True:
        all_items = fetch_rss_items() + fetch_abusech_items()
        for item in all_items:
            summary, severity = ai.summarize_and_score(item.title, item.description, item.source)
            db.upsert_news(
                title=item.title,
                link=item.link,
                source=item.source,
                category=item.category,
                severity=severity,
                summary=summary,
            )

        cves = fetch_latest_cves(limit=40)
        for cve in cves:
            db.upsert_cve(cve.cve_id, cve.summary, cve.severity)

        await asyncio.sleep(COLLECT_INTERVAL_SECONDS)


async def _run() -> None:
    collector_task = asyncio.create_task(run_collector_loop())
    config = uvicorn.Config("api:app", host="0.0.0.0", port=int(os.getenv("API_PORT", "8000")), reload=False)
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())
    await asyncio.gather(collector_task, api_task)


if __name__ == "__main__":
    asyncio.run(_run())
