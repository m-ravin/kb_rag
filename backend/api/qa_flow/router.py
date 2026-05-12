"""
Q&A Flow API — the main orchestrator.

When a user sends a question, this endpoint runs the full pipeline:
  1. Safety check (PII + content)
  2. Question type detection
  3. Keyword extraction
  4. Hybrid search → relevant PIL chunks
  5. Answer generation
  6. Wording tuning + compliance check
  7. Language check
  8. Log everything

Think of it as a smart receptionist who takes your question, consults
the right experts, and gives you a polished, safe, accurate answer.
"""

import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from backend.core.limiter import limiter
from backend.models.qa import AskRequest, AskResponse, QuestionType
from backend.services import llm_service, search_service, safety_service, monitoring_service

router = APIRouter(prefix="/qa", tags=["Q&A Flow"])


@router.post("/ask", response_model=AskResponse)
@limiter.limit("30/minute")
async def ask(http_request: Request, request: AskRequest) -> AskResponse:
    """
    Full RAG pipeline: question → safety → search → LLM → answer.
    This is the endpoint the chat UI calls.
    """
    t_start = time.monotonic()
    session_id = request.session_id or str(uuid.uuid4())

    # ── Step 1: Detect and mask PII in a single Presidio call ────────────────
    # screen_pii calls /redact once so has_pii and safe_question come from the
    # same response. Calling detect_pii + mask_pii separately would make two
    # round-trips and allow a race on a flapping Presidio service (see ADR-0011).
    has_pii, _, safe_question = await safety_service.screen_pii(request.question)

    # ── Step 2: Check the safe question for harmful content ───────────────────
    is_safe, unsafe_category = await safety_service.check_content_safety(safe_question)
    if not is_safe:
        return AskResponse(
            session_id=session_id,
            question=safe_question,
            answer=f"I'm unable to respond to this type of request ({unsafe_category}).",
            question_type=QuestionType.UNKNOWN,
            sources=[],
            language=request.language,
            tokens_used=0,
            latency_ms=round((time.monotonic() - t_start) * 1000, 2),
            flagged_pii=has_pii,
            flagged_unsafe=True,
            created_at=datetime.now(timezone.utc),
        )

    # ── Step 3: Understand the question type (using masked question) ──────────
    question_type = await llm_service.detect_question_type(safe_question)

    # ── Step 4: Extract search keywords ───────────────────────────────────────
    keywords = await llm_service.extract_keywords(safe_question)
    keyword_query = " ".join(keywords) if keywords else safe_question

    # ── Step 5: Hybrid search (vector + keyword) ──────────────────────────────
    chunks = await search_service.hybrid_search(keyword_query, top_k=request.max_chunks)

    # ── Step 6: Expand context using graph neighbours ─────────────────────────
    if chunks:
        seed_ids = [c.chunk_id for c in chunks[:3]]
        graph_chunks = await search_service.graph_search(seed_ids, top_k=2)
        # Merge without duplicates
        existing_ids = {c.chunk_id for c in chunks}
        for gc in graph_chunks:
            if gc.chunk_id not in existing_ids:
                chunks.append(gc)

    # ── Step 7: Generate answer from retrieved chunks ─────────────────────────
    total_tokens = 0
    answer, tokens = await llm_service.generate_answer(
        safe_question, chunks, request.language
    )
    total_tokens += tokens

    # ── Step 8: Tune wording to be clear and professional ────────────────────
    answer, wording_tokens = await llm_service.tune_wording(answer, tone="professional")
    total_tokens += wording_tokens

    # ── Step 9: Compliance check ──────────────────────────────────────────────
    is_compliant, _ = await llm_service.check_compliance(answer)
    if not is_compliant:
        answer = (
            "I can provide general information from the knowledge base, "
            "but please verify with an authoritative source before acting on it. "
            + answer
        )

    # ── Step 10: Detect output language ──────────────────────────────────────
    detected_lang = await llm_service.detect_language(answer)

    latency_ms = round((time.monotonic() - t_start) * 1000, 2)

    # ── Step 11: Log masked question to Cosmos MongoDB (never the raw PII) ─────
    await monitoring_service.log_qa_interaction(
        session_id=session_id,
        question=safe_question,
        answer=answer,
        question_type=question_type.value,
        sources=[c.model_dump() for c in chunks],
        tokens_used=total_tokens,
        latency_ms=latency_ms,
        flagged_pii=has_pii,
        flagged_unsafe=False,
        language=detected_lang,
    )

    return AskResponse(
        session_id=session_id,
        question=safe_question,
        answer=answer,
        question_type=question_type,
        sources=chunks,
        language=detected_lang,
        tokens_used=total_tokens,
        latency_ms=latency_ms,
        flagged_pii=has_pii,
        flagged_unsafe=False,
        created_at=datetime.now(timezone.utc),
    )
