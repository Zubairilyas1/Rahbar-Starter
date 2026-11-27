"""POST /api/ask and POST /api/retrieve. The Ingress sends /api/* here unchanged."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..logjson import request_id_var
from ..schemas import AskRequest, AskResponse, RetrievedPassage, RetrieveResponse
from ..services.answer import answer_question, retrieve_only

router = APIRouter(prefix="/api")

# The evaluation suite sends this header so repeated runs measure the pipeline,
# not the semantic cache (Part B stochasticity). Normal users never send it.
NO_CACHE_HEADER = "x-ragops-no-cache"


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request) -> AskResponse:
    state = request.app.state
    use_cache = request.headers.get(NO_CACHE_HEADER, "") not in ("1", "true", "yes")
    return answer_question(body.question, state.retriever, state.provider, state.settings, use_cache=use_cache)


@router.get("/info")
def info(request: Request) -> dict[str, object]:
    """Which pipeline is serving: the eval suite records it in every result file, and
    it makes a rollout / rollout undo visible without opening a trace."""
    s = request.app.state.settings
    return {
        "pipeline_version": s.pipeline_version,
        "collection": s.collection,
        "collection_version": s.collection_version,
        "embed_model": s.embed_model,
        "embed_version": s.embed_version,
        "llm_provider": s.llm_provider,
        "llm_model": s.llm_model,
        "top_k": s.top_k,
        "relevance_floor": s.relevance_floor,
        "temperature": s.temperature,
        "seed": s.llm_seed,
    }


@router.post("/retrieve", response_model=RetrieveResponse)
def retrieve(body: AskRequest, request: Request) -> RetrieveResponse:
    """Retrieval only (no generation): the component-level test of Part B uses it,
    and the faithfulness judge reads the same context the generator received."""
    state = request.app.state
    passages, filters = retrieve_only(body.question, state.retriever, state.settings)
    return RetrieveResponse(
        request_id=request_id_var.get(),
        collection=state.settings.collection,
        filters_applied=filters,
        passages=[
            RetrievedPassage(chunk_id=p.chunk_id, source=p.source, section=p.section, page=p.page,
                             score=p.score, doc_version=p.doc_version, text=p.text)
            for p in passages
        ],
    )
