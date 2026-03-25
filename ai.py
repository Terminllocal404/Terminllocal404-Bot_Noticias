"""OpenAI-powered summarization helpers."""

from __future__ import annotations

import logging
from typing import Optional

from openai import OpenAI

LOGGER = logging.getLogger(__name__)


class AISummarizer:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def summarize(self, title: str, description: str, source: str) -> str:
        prompt = (
            "You are a defensive cybersecurity analyst. Summarize this item in 2-3 short lines "
            "with focus on impact, affected systems, and risk. No illegal advice.\n\n"
            f"Source: {source}\n"
            f"Title: {title}\n"
            f"Description: {description or 'No description available.'}"
        )
        try:
            response = self.client.responses.create(
                model=self.model,
                input=prompt,
                max_output_tokens=120,
                temperature=0.2,
            )
            text = response.output_text.strip()
            return text if text else "No summary generated."
        except Exception as exc:  # graceful fallback
            LOGGER.warning("OpenAI summarization failed: %s", exc)
            fallback = description.strip() if description else "No description available."
            return (fallback[:250] + "...") if len(fallback) > 250 else fallback


def short_summary(summary: Optional[str], limit: int = 400) -> str:
    if not summary:
        return "No summary available."
    return summary if len(summary) <= limit else summary[: limit - 3] + "..."
