"""
Task APIs — individual, reusable AI building blocks.

Each endpoint here does one specific job. The Q&A Flow calls these internally,
but they're also exposed directly so developers can use them standalone.

Think of these as tools in a toolbox: each one does one thing very well.
"""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.core.auth import get_current_user
from backend.models.qa import TaskRequest, TaskResponse
from backend.services import llm_service, safety_service

router = APIRouter(
    prefix="/tasks",
    tags=["Task APIs"],
    dependencies=[Depends(get_current_user)],
)

_VALID_TONES = {"professional", "friendly", "simple"}
_VALID_LANGUAGES = {"en", "ms", "zh", "ta", "fr", "de", "es", "ar", "pt", "id"}


@router.post("/content-safety", response_model=TaskResponse)
async def check_content_safety(req: TaskRequest) -> TaskResponse:
    """
    Checks if text contains harmful content (hate speech, violence, etc.)
    Returns {safe: bool, category: str}
    """
    t = time.monotonic()
    is_safe, category = await safety_service.check_content_safety(req.text)
    return TaskResponse(
        result={"safe": is_safe, "category": category},
        latency_ms=round((time.monotonic() - t) * 1000, 2),
    )


@router.post("/pii-detection", response_model=TaskResponse)
async def detect_pii(req: TaskRequest) -> TaskResponse:
    """
    Detects personally identifiable information (names, emails, phone numbers).
    Returns {has_pii: bool, detected_patterns: list[str]}
    """
    t = time.monotonic()
    has_pii, patterns = await safety_service.detect_pii(req.text)
    return TaskResponse(
        result={"has_pii": has_pii, "detected_patterns": patterns},
        latency_ms=round((time.monotonic() - t) * 1000, 2),
    )


@router.post("/question-understanding", response_model=TaskResponse)
async def understand_question(req: TaskRequest) -> TaskResponse:
    """
    Analyses a question to understand user intent.
    Returns {type: str, keywords: list[str]}
    """
    t = time.monotonic()
    q_type = await llm_service.detect_question_type(req.text)
    keywords = await llm_service.extract_keywords(req.text)
    return TaskResponse(
        result={"type": q_type.value, "keywords": keywords},
        latency_ms=round((time.monotonic() - t) * 1000, 2),
    )


@router.post("/question-type-detection", response_model=TaskResponse)
async def detect_question_type(req: TaskRequest) -> TaskResponse:
    """
    Classifies a question: faq / procedural / factual / comparison / unknown.
    """
    t = time.monotonic()
    q_type = await llm_service.detect_question_type(req.text)
    return TaskResponse(
        result={"question_type": q_type.value},
        latency_ms=round((time.monotonic() - t) * 1000, 2),
    )


@router.post("/query-keyword-extraction", response_model=TaskResponse)
async def extract_keywords(req: TaskRequest) -> TaskResponse:
    """
    Pulls out key search terms from a question or statement.
    Useful for improving search precision.
    """
    t = time.monotonic()
    keywords = await llm_service.extract_keywords(req.text)
    return TaskResponse(
        result={"keywords": keywords},
        latency_ms=round((time.monotonic() - t) * 1000, 2),
    )


@router.post("/translation", response_model=TaskResponse)
async def translate(req: TaskRequest) -> TaskResponse:
    """
    Translates text to the target language specified in options.language.
    Example: {"language": "ms"} → translates to Bahasa Malaysia.
    """
    t = time.monotonic()
    target_lang = req.options.get("language", "en")
    if target_lang not in _VALID_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Invalid language. Must be one of: {sorted(_VALID_LANGUAGES)}")
    translated, tokens = await llm_service.translate_text(req.text, target_lang)
    return TaskResponse(
        result={"translated_text": translated, "target_language": target_lang},
        tokens_used=tokens,
        latency_ms=round((time.monotonic() - t) * 1000, 2),
    )


@router.post("/summarizer", response_model=TaskResponse)
async def summarise(req: TaskRequest) -> TaskResponse:
    """
    Condenses long text into a short summary.
    options.max_sentences controls how many sentences (default 5).
    """
    t = time.monotonic()
    max_sentences = req.options.get("max_sentences", 5)
    if not isinstance(max_sentences, int) or not (1 <= max_sentences <= 20):
        raise HTTPException(status_code=400, detail="max_sentences must be an integer between 1 and 20")
    summary, tokens = await llm_service.summarise_text(req.text, max_sentences)
    return TaskResponse(
        result={"summary": summary},
        tokens_used=tokens,
        latency_ms=round((time.monotonic() - t) * 1000, 2),
    )


@router.post("/wording-tuning", response_model=TaskResponse)
async def tune_wording(req: TaskRequest) -> TaskResponse:
    """
    Rewrites text in the desired tone.
    options.tone: "professional" | "friendly" | "simple" (default: professional)
    """
    t = time.monotonic()
    tone = req.options.get("tone", "professional")
    if tone not in _VALID_TONES:
        raise HTTPException(status_code=400, detail=f"Invalid tone. Must be one of: {sorted(_VALID_TONES)}")
    tuned, tokens = await llm_service.tune_wording(req.text, tone)
    return TaskResponse(
        result={"tuned_text": tuned, "tone": tone},
        tokens_used=tokens,
        latency_ms=round((time.monotonic() - t) * 1000, 2),
    )


@router.post("/message-template-parser", response_model=TaskResponse)
async def parse_template(req: TaskRequest) -> TaskResponse:
    """
    Fills template variables in a message using provided options as the variable map.
    Example: template "Dear {{name}}" + options {"name": "Alice"} → "Dear Alice"
    """
    t = time.monotonic()
    result = req.text
    for key, value in req.options.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return TaskResponse(
        result={"rendered": result},
        latency_ms=round((time.monotonic() - t) * 1000, 2),
    )


@router.post("/compliance-check", response_model=TaskResponse)
async def compliance_check(req: TaskRequest) -> TaskResponse:
    """
    Checks whether a medical response meets compliance guidelines.
    Returns {compliant: bool, reason: str}
    """
    t = time.monotonic()
    is_compliant, reason = await llm_service.check_compliance(req.text)
    return TaskResponse(
        result={"compliant": is_compliant, "reason": reason},
        latency_ms=round((time.monotonic() - t) * 1000, 2),
    )


@router.post("/language-check", response_model=TaskResponse)
async def check_language(req: TaskRequest) -> TaskResponse:
    """Detects the language of the input text. Returns ISO 639-1 code."""
    t = time.monotonic()
    lang = await llm_service.detect_language(req.text)
    return TaskResponse(
        result={"language": lang},
        latency_ms=round((time.monotonic() - t) * 1000, 2),
    )
