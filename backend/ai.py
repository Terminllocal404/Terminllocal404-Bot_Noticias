"""OpenAI summarization and risk extraction."""

from __future__ import annotations

import json
import os

from openai import OpenAI


class AISummarizer:
    def __init__(self) -> None:
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def summarize_and_score(self, title: str, description: str, source: str) -> tuple[str, str]:
        prompt = (
            "You are a cybersecurity analyst. Return strict JSON with keys summary and severity. "
            "Summary must be 2-3 short defensive lines. Severity must be one of LOW, MEDIUM, HIGH, CRITICAL. "
            "Do not include offensive guidance.\n"
            f"Source: {source}\n"
            f"Title: {title}\n"
            f"Description: {description or 'No description provided'}"
        )
        try:
            response = self.client.responses.create(
                model=self.model,
                input=prompt,
                temperature=0.2,
                max_output_tokens=220,
            )
            raw = response.output_text.strip()
            payload = json.loads(raw)
            summary = str(payload.get("summary", "No summary generated.")).strip()
            severity = str(payload.get("severity", "MEDIUM")).upper()
            if severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                severity = "MEDIUM"
            return summary, severity
        except Exception:
            fallback = (description or "No description provided").strip()
            summary = fallback[:350] + ("..." if len(fallback) > 350 else "")
            return summary, "MEDIUM"
