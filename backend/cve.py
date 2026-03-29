"""CVE collector."""

from __future__ import annotations

from dataclasses import dataclass

import requests

CVE_API_URL = "https://cve.circl.lu/api/last"


@dataclass
class CVEItem:
    cve_id: str
    summary: str
    severity: str


def _to_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _severity(cvss: float, summary: str) -> str:
    text = (summary or "").lower()
    if cvss >= 9.0 or "critical" in text:
        return "CRITICAL"
    if cvss >= 7.0 or "rce" in text or "zero-day" in text:
        return "HIGH"
    if cvss >= 4.0:
        return "MEDIUM"
    return "LOW"


def fetch_latest_cves(limit: int = 30) -> list[CVEItem]:
    try:
        response = requests.get(CVE_API_URL, timeout=20)
        response.raise_for_status()
        entries = response.json()
    except Exception:
        return []

    results: list[CVEItem] = []
    for raw in entries[: limit * 2]:
        cve_id = raw.get("id") or raw.get("cve") or "UNKNOWN-CVE"
        summary = raw.get("summary") or "No summary provided."
        cvss = _to_float(raw.get("cvss") or raw.get("cvss3"))
        results.append(CVEItem(cve_id=cve_id, summary=summary, severity=_severity(cvss, summary)))

    unique: dict[str, CVEItem] = {item.cve_id: item for item in results}
    return list(unique.values())[:limit]
