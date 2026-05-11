"""
Presidio PII Detection Service

Standalone microservice that wraps Microsoft Presidio's analyzer and anonymizer.
Any service in the platform can call this instead of bundling Presidio locally.

Endpoints
---------
GET  /health           Liveness probe — returns 200 when the spaCy model is loaded
GET  /entities         List all supported entity types (built-in + custom)
POST /analyze          Detect PII entities and return their positions + scores
POST /anonymize        Replace PII in text using pre-computed analyzer results
POST /redact           Combined: analyze + anonymize in a single request (most common)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerResult
from presidio_anonymizer import AnonymizerEngine
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── Custom recognizers ────────────────────────────────────────────────────────
# These extend Presidio's built-in set (PERSON, EMAIL_ADDRESS, PHONE_NUMBER, etc.)

_MY_NRIC_RECOGNIZER = PatternRecognizer(
    supported_entity="MY_NRIC",
    patterns=[
        Pattern(
            name="MY_NRIC_dashes",
            # 6 digits – 2 digits – 4 digits (e.g. 870315-07-1234)
            regex=r"\b\d{6}-\d{2}-\d{4}\b",
            score=0.95,
        ),
        Pattern(
            name="MY_NRIC_nodashes",
            # 12 contiguous digits, not part of a longer number
            regex=r"(?<!\d)\d{12}(?!\d)",
            score=0.75,
        ),
    ],
)

# ── Engine initialisation ─────────────────────────────────────────────────────
# AnalyzerEngine loads the spaCy language model on first construction.
# Placing this at module level means it loads once when the container starts,
# not on the first request (which would cause a slow first response).

_analyzer = AnalyzerEngine()
_analyzer.registry.add_recognizer(_MY_NRIC_RECOGNIZER)

_anonymizer = AnonymizerEngine()


# ── Pydantic models ───────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    text: str
    language: str = "en"
    entities: list[str] | None = None  # None = detect all entity types


class AnalyzeResultItem(BaseModel):
    entity_type: str
    start: int
    end: int
    score: float


class AnonymizeRequest(BaseModel):
    text: str
    analyzer_results: list[AnalyzeResultItem]


class AnonymizeResponse(BaseModel):
    text: str
    items: list[dict]


class RedactRequest(BaseModel):
    text: str
    language: str = "en"


class RedactResponse(BaseModel):
    original_text: str
    redacted_text: str
    entities_found: list[str]
    has_pii: bool


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Presidio PII service ready — spaCy model loaded.")
    yield


app = FastAPI(
    title="Presidio PII Detection Service",
    version="1.0.0",
    description=(
        "Standalone PII detection and anonymization service. "
        "Built on Microsoft Presidio + spaCy. Supports custom Malaysian NRIC recognition."
    ),
    lifespan=lifespan,
)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
def health() -> dict:
    """Liveness probe — returns 200 once the spaCy model is loaded."""
    return {"status": "healthy"}


@app.get("/entities", tags=["Meta"])
def list_entities() -> dict:
    """Returns all entity types this service can detect."""
    entities: set[str] = set()
    for recognizer in _analyzer.registry.recognizers:
        entities.update(recognizer.supported_entities)
    return {"entities": sorted(entities)}


@app.post("/analyze", response_model=list[AnalyzeResultItem], tags=["PII"])
def analyze(req: AnalyzeRequest) -> list[AnalyzeResultItem]:
    """
    Detects PII entities in text and returns their positions and confidence scores.
    Use this when you need fine-grained control over what gets anonymized.
    """
    try:
        results = _analyzer.analyze(
            text=req.text[:5000],
            language=req.language,
            entities=req.entities,
        )
    except Exception as exc:
        logger.exception("Analyzer error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")

    return [
        AnalyzeResultItem(
            entity_type=r.entity_type,
            start=r.start,
            end=r.end,
            score=r.score,
        )
        for r in results
    ]


@app.post("/anonymize", response_model=AnonymizeResponse, tags=["PII"])
def anonymize(req: AnonymizeRequest) -> AnonymizeResponse:
    """
    Replaces detected PII with [REDACTED] tokens given pre-computed analyzer results.
    Use /analyze first, then /anonymize if you need to inspect entities before masking.
    """
    if not req.analyzer_results:
        return AnonymizeResponse(text=req.text, items=[])

    recognizer_results = [
        RecognizerResult(
            entity_type=r.entity_type,
            start=r.start,
            end=r.end,
            score=r.score,
        )
        for r in req.analyzer_results
    ]

    try:
        # Truncate to the same 5000-char limit used by /analyze so that
        # offset positions in analyzer_results are valid for this text slice.
        result = _anonymizer.anonymize(
            text=req.text[:5000], analyzer_results=recognizer_results
        )
    except Exception as exc:
        logger.exception("Anonymizer error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Anonymization failed: {exc}")

    return AnonymizeResponse(
        text=result.text,
        items=[
            {
                "entity_type": item.entity_type,
                "operator": item.operator,
                "start": item.start,
                "end": item.end,
                "text": item.text,
            }
            for item in result.items
        ],
    )


@app.post("/redact", response_model=RedactResponse, tags=["PII"])
def redact(req: RedactRequest) -> RedactResponse:
    """
    Convenience endpoint: analyze + anonymize in a single call.
    This is the endpoint most callers should use.
    Returns the redacted text and the list of entity types that were found.
    """
    try:
        analyzer_results = _analyzer.analyze(
            text=req.text[:5000],
            language=req.language,
        )
    except Exception as exc:
        logger.exception("Analyzer error during redact: %s", exc)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")

    if not analyzer_results:
        return RedactResponse(
            original_text=req.text,
            redacted_text=req.text,
            entities_found=[],
            has_pii=False,
        )

    entity_types = list({r.entity_type for r in analyzer_results})

    try:
        anonymized = _anonymizer.anonymize(
            text=req.text[:5000], analyzer_results=analyzer_results
        )
    except Exception as exc:
        logger.exception("Anonymizer error during redact: %s", exc)
        raise HTTPException(status_code=500, detail=f"Anonymization failed: {exc}")

    return RedactResponse(
        original_text=req.text,
        redacted_text=anonymized.text,
        entities_found=entity_types,
        has_pii=True,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
