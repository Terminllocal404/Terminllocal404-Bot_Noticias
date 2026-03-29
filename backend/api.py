"""FastAPI endpoints for Cyber Intelligence Platform."""

from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from db import Database, aggregate_severity_counts

app = FastAPI(title="Cyber Intelligence Platform API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _db() -> Database:
    return Database()


@app.get("/news")
def get_news(
    severity: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    db = _db()
    items = db.get_news(severity=severity, search=search, limit=limit)
    return {"count": len(items), "items": items}


@app.get("/news/{category}")
def get_news_by_category(
    category: str,
    severity: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    db = _db()
    items = db.get_news(category=category.lower(), severity=severity, search=search, limit=limit)
    return {"count": len(items), "items": items}


@app.get("/cves")
def get_cves(
    severity: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    db = _db()
    items = db.get_cves(severity=severity, limit=limit)
    return {"count": len(items), "items": items}


@app.get("/alerts")
def get_alerts(limit: int = Query(default=100, ge=1, le=500)):
    db = _db()
    items = db.get_alerts(limit=limit)
    return {"count": len(items), "items": items}


@app.get("/trends")
def get_trends(limit: int = Query(default=50, ge=1, le=500)):
    db = _db()
    items = db.get_news(limit=limit)
    severity = aggregate_severity_counts(items)
    by_category: dict[str, int] = {}
    for item in items:
        cat = item["category"]
        by_category[cat] = by_category.get(cat, 0) + 1

    return {
        "total_items": len(items),
        "severity_counts": severity,
        "category_counts": by_category,
        "latest": items[:10],
    }
