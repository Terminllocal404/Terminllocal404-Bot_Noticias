"""CVE feed fetcher and basic severity ranking."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

import requests

LOGGER = logging.getLogger(__name__)

CVE_API_URL = "https://cve.circl.lu/api/last"


@dataclass
class CVEItem:
    cve_id: str
    summary: str
    severity: str
    cvss: float


def _to_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def classify_severity(cvss: float, summary: str) -> str:
    text = (summary or "").lower()
    if cvss >= 9.0 or "critical" in text or "actively exploited" in text:
        return "critical"
    if cvss >= 7.0:
        return "high"
    if cvss >= 4.0:
        return "medium"
    return "low"


def fetch_latest_cves(limit: int = 10) -> List[CVEItem]:
    try:
        response = requests.get(CVE_API_URL, timeout=20)
        response.raise_for_status()
        raw_items = response.json()
    except Exception as exc:
        LOGGER.error("Failed to fetch CVEs: %s", exc)
        return []

    cves: List[CVEItem] = []
    for raw in raw_items[: limit * 3]:
        cve_id = raw.get("id") or raw.get("cve") or "UNKNOWN-CVE"
        summary = raw.get("summary", "No summary provided.")
        cvss = _to_float(raw.get("cvss") or raw.get("cvss3"))
        severity = classify_severity(cvss, summary)
        cves.append(CVEItem(cve_id=cve_id, summary=summary, severity=severity, cvss=cvss))

    cves.sort(key=lambda x: x.cvss, reverse=True)
    return cves[:limit]
