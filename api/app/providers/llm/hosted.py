"""Hosted free-tier provider (Groq, Google AI Studio, OpenRouter). Yours to build.

The key arrives as LLM_API_KEY from a Kubernetes Secret created on the command
line. It never appears in a file you commit, and never in a log line.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from ...config import Settings
from ...schemas import Answer, Passage

log = logging.getLogger("rahbar.llm.hosted")

SYSTEM_PROMPT = """You are RAHBAR, an evidence-grounded academic assistant.
Answer ONLY using the provided numbered evidence passages.
If the information required to answer the question is not present in the evidence passages:
- Set answered_from_context to false.
- Set answer to "I do not have sufficient information in the provided documents to answer this question."
- Set citations to an empty list [].
- Set confidence to "low".

Output MUST be valid JSON adhering to:
{
  "reasoning": "step-by-step thinking",
  "answer": "grounded response text",
  "citations": [{"source": "filename.pdf", "section": "section name", "page": 1}],
  "answered_from_context": true/false,
  "confidence": "high"/"medium"/"low"
}
"""

SAFE_FALLBACK = Answer(
    reasoning="Fallback activated due to hosted schema validation failure.",
    answer="I do not have sufficient verified information in the documents to answer this question.",
    citations=[],
    answered_from_context=False,
    confidence="low",
)


class HostedProvider:
    name = "hosted"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _build_prompt(self, question: str, passages: list[Passage]) -> str:
        evidence_text = "\n\n".join(
            f"Passage [{idx + 1}] (Source: {p.source}, Section: {p.section}, Page: {p.page}, Score: {p.score}):\n{p.text}"
            for idx, p in enumerate(passages)
        )
        return (
            f"Evidence passages:\n{evidence_text}\n\n"
            f"User Question: {question}\n\n"
            "Respond strictly in JSON matching the schema."
        )

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        prompt = self._build_prompt(question, passages)
        base = self.settings.hosted_base_url.rstrip("/")
        url = f"{base}/chat/completions" if base else "https://api.openai.com/v1/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.llm_api_key}",
        }

        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "response_format": {"type": "json_object"},  # Constrained decoding parameter
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.settings.temperature,
        }

        # Attempt call with retry on validation error
        for attempt in range(2):
            try:
                with httpx.Client(timeout=self.settings.llm_timeout) as client:
                    resp = client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                    parsed = json.loads(content)
                    return Answer.model_validate(parsed)
            except (ValidationError, json.JSONDecodeError) as val_err:
                log.warning(f"Hosted generation validation error (attempt {attempt + 1}): {val_err}")
                if attempt == 0:
                    payload["messages"].append(
                        {"role": "user", "content": "Return valid JSON only matching the schema."}
                    )
                    continue
            except Exception as exc:
                log.error(f"Hosted provider request error: {exc}")
                break

        log.error("Hosted generation failed; returning safe fallback.")
        return SAFE_FALLBACK
