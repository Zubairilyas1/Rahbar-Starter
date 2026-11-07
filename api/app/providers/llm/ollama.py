"""Ollama provider: ollama-host or ollama-incluster (section 3.5). Yours to build."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from ...config import Settings
from ...schemas import Answer, Passage

log = logging.getLogger("rahbar.llm.ollama")

SYSTEM_PROMPT = """You are RAHBAR, an evidence-grounded academic assistant.
Answer ONLY using the provided numbered evidence passages.
If the information required to answer the question is not present in the evidence passages:
- Set answered_from_context to false.
- Set answer to "I do not have sufficient information in the provided documents to answer this question."
- Set citations to an empty list [].
- Set confidence to "low".

Rules:
1. Every claim in your answer must be supported by the evidence.
2. Only cite passages that directly contain the facts mentioned.
3. Each citation must match the source, section, and page of an evidence passage.
4. Output MUST be valid JSON conforming to the following schema:
{
  "reasoning": "step-by-step thinking",
  "answer": "grounded response text",
  "citations": [{"source": "filename.pdf", "section": "section name", "page": 1}],
  "answered_from_context": true/false,
  "confidence": "high"/"medium"/"low"
}
"""

SAFE_FALLBACK = Answer(
    reasoning="Fallback activated due to schema validation failure.",
    answer="I do not have sufficient verified information in the documents to answer this question.",
    citations=[],
    answered_from_context=False,
    confidence="low",
)


class OllamaProvider:
    name = "ollama"

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
            "Provide your grounded answer as a JSON object adhering to the schema."
        )

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        prompt = self._build_prompt(question, passages)
        url = f"{self.settings.ollama_url.rstrip('/')}/api/chat"

        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "format": "json",  # Constrained decoding parameter
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "options": {
                "temperature": self.settings.temperature,
            },
            "stream": False,
        }

        # Attempt call with retry on validation error
        for attempt in range(2):
            try:
                with httpx.Client(timeout=self.settings.llm_timeout) as client:
                    resp = client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    content = data.get("message", {}).get("content", "{}")
                    parsed = json.loads(content)
                    return Answer.model_validate(parsed)
            except (ValidationError, json.JSONDecodeError) as val_err:
                log.warning(f"Ollama generation validation error (attempt {attempt + 1}): {val_err}")
                if attempt == 0:
                    payload["messages"].append(
                        {"role": "user", "content": "Your previous response was not valid JSON conforming to the Answer schema. Output strictly JSON only."}
                    )
                    continue
            except Exception as exc:
                log.error(f"Ollama request error: {exc}")
                break

        log.error("Ollama generation failed or invalid after retry; returning safe fallback.")
        return SAFE_FALLBACK
