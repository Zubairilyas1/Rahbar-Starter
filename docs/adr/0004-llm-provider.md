# ADR 0004: Pluggable LLM Interface and Constrained Schema Enforcement

## Status
Accepted — November 2026

## Context
Deploying RAG across developer laptops, CI runners, and Kubernetes clusters requires adaptability across different model providers. Offline CI and automated unit tests must never incur external API costs or fail due to network timeouts; conversely, production deployments require high-capability local models (`llama3.2:3b` via Ollama) or hosted endpoints (Groq / OpenRouter). Furthermore, LLMs inherently produce unstructured natural language, which can easily break downstream API contracts, hallucinate ungrounded citations, or leak prompt injection vectors.

## Decision
We abstract model generation behind a unified `LLMProvider` interface configured via the `LLM_PROVIDER` environment variable (`stub | ollama-host | ollama-incluster | hosted`):
1. **Offline Stub**: `StubProvider` generates deterministic grounded responses for automated CI and unit tests without external network dependencies.
2. **Constrained JSON Decoding**: All production providers enforce JSON output mode (`format="json"` or `response_format={"type": "json_object"}`).
3. **Pydantic Validation with Safe Fallback**: Generated outputs are validated against the `Answer` schema. A validation failure triggers an automatic single-retry with an explicit format correction prompt. If the retry fails, the system returns a safe, structured abstention response rather than surfacing a 500 server error.
4. **Secret Management**: Sensitive API keys arrive strictly via Kubernetes Secrets (`LLM_API_KEY`), never written to disk or recorded in log outputs.

## Options considered
1. **Direct OpenAI SDK Binding**: Rejected because it locks the architecture to proprietary endpoints, preventing offline testing and in-cluster Ollama deployment.
2. **Unconstrained Text Prompting with Regex Parsing**: Rejected because small phrasing variations in the LLM response frequently break extraction, leading to unhandled runtime exceptions.

## Consequences
- **Positive**: 100% deterministic test pass rates in CI using the stub provider; runtime resilience against malformed model replies; clean zero-trust secret management.
- **Negative**: Requires maintaining format schemas across both Ollama and hosted endpoint variants.
