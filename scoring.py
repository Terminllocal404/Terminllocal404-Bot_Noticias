"""Severity scoring utilities for intelligence items."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeverityResult:
    score: int
    level: str


def compute_severity_score(text: str) -> SeverityResult:
    blob = (text or "").lower()
    score = 0

    if "critical" in blob or "zero-day" in blob:
        score += 2
    if "rce" in blob or "remote code execution" in blob:
        score += 2
    if "linux kernel" in blob or "windows kernel" in blob or "kernel" in blob:
        score += 1

    if score >= 5:
        level = "CRITICAL"
    elif score >= 3:
        level = "HIGH"
    elif score >= 1:
        level = "MEDIUM"
    else:
        level = "LOW"

    return SeverityResult(score=score, level=level)
