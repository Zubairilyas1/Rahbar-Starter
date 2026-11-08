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
Answer questions using ONLY the provided numbered evidence passages.

CRITICAL RULES:
1. Strict Grounding: Answer strictly using explicit facts found in the evidence passages. NEVER invent, fabricate, or guess numbers, route numbers, codes, dates, or percentages that are not explicitly written in the passages. If the passages mention transport or buses but do NOT state route numbers, you MUST ABSTAIN.
2. Abstention: If the evidence passages DO NOT contain the exact answer for the specific question:
   - "answered_from_context": false
   - "confidence": "low"
   - "answer": "I do not have sufficient information in the provided documents to answer this question."
   - "citations": []
3. Grounded Answer: When evidence passages DO contain the direct answer:
   - "answered_from_context": true
   - "confidence": "high"
   - "answer": Direct, factual response.
   - "citations": List of citations with exact "source", "section", and "page" from the matching passages.

Output MUST be valid JSON conforming to the following schema:
{
  "reasoning": "step-by-step thinking",
  "answer": "grounded response text",
  "citations": [{"source": "filename.pdf", "section": "section name", "page": 1}],
  "answered_from_context": true,
  "confidence": "high"
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
                    if isinstance(parsed, dict):
                        if "citations" not in parsed or not isinstance(parsed["citations"], list):
                            parsed["citations"] = []
                        if "answered_from_context" not in parsed:
                            parsed["answered_from_context"] = bool(parsed.get("citations"))
                        if "confidence" not in parsed or parsed["confidence"] not in ("high", "medium", "low"):
                            parsed["confidence"] = "high" if parsed.get("citations") else "low"
                        if "reasoning" not in parsed:
                            parsed["reasoning"] = ""
                        if "answer" not in parsed:
                            parsed["answer"] = ""
                    ans = Answer.model_validate(parsed)
                    # Align flags if model answered factually with valid citations
                    abstention_indicators = (
                        "do not have sufficient",
                        "insufficient information",
                        "do not provide sufficient",
                        "not explicitly stated",
                        "not sufficient",
                        "cannot answer",
                        "no information",
                        "not covered",
                        "not found",
                    )
                    is_abstain = any(w in ans.answer.lower() for w in abstention_indicators)
                    if is_abstain or not ans.citations:
                        ans.answered_from_context = False
                        ans.confidence = "low"
                        ans.citations = []
                    else:
                        ans.answered_from_context = True
                        if ans.confidence == "low":
                            ans.confidence = "high"
                    return ans
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
