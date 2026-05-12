"""
Safety Service — PII detection and content safety screening.

Every question and answer passes through here before being processed or returned.
Like a security guard who checks everyone entering or leaving a building.

PII detection delegates to the standalone Presidio microservice (presidio-service).
No PII analysis runs in-process — the microservice can be called by any platform service.
"""

import logging

import httpx

from backend.core.config import get_settings

logger = logging.getLogger(__name__)


async def detect_pii(text: str) -> tuple[bool, list[str]]:
    """
    Calls the Presidio service /analyze endpoint to detect PII entity types.
    Returns (has_pii, list_of_entity_types).

    FAIL-CLOSED: on any connectivity failure returns (True, ["UNKNOWN"]) so the
    caller proceeds to call mask_pii, which will raise HTTP 503 if Presidio is
    still down. Raw PII never reaches the LLM — see ADR-0011.
    """
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.post(
                f"{s.presidio_endpoint}/analyze",
                json={"text": text[:5000], "language": "en"},
            )
            resp.raise_for_status()
            results = resp.json()
            entity_types = list({r["entity_type"] for r in results})
            return bool(results), entity_types
    except Exception as exc:
        logger.error("Presidio /analyze unreachable — assuming PII present: %s", exc)
        return True, ["UNKNOWN"]


async def screen_pii(text: str) -> tuple[bool, list[str], str]:
    """
    Detects and masks PII in a single Presidio /redact call.
    Returns (has_pii, entity_types, masked_text).

    Use this in the Q&A pipeline instead of calling detect_pii + mask_pii
    separately — two round-trips allow a race on a flapping service where
    /analyze returns the fail-closed sentinel but /redact then succeeds with
    no entities found, silently returning unmasked text.

    FAIL-CLOSED: raises HTTP 503 on any connectivity failure.
    """
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.post(
                f"{s.presidio_endpoint}/redact",
                json={"text": text[:5000], "language": "en"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["has_pii"], data["entities_found"], data["redacted_text"]
    except Exception as exc:
        logger.error("Presidio /redact unreachable — blocking request: %s", exc)
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail="PII screening service temporarily unavailable. Please try again shortly.",
        )


async def mask_pii(text: str) -> str:
    """
    Calls the Presidio service /redact endpoint to replace all PII with [REDACTED].
    Call this before sending user input to the LLM or storing it in logs.

    FAIL-CLOSED: raises HTTP 503 on any connectivity failure so the Q&A pipeline
    is blocked rather than passing raw PII to the LLM — see ADR-0011.
    """
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.post(
                f"{s.presidio_endpoint}/redact",
                json={"text": text[:5000], "language": "en"},
            )
            resp.raise_for_status()
            return resp.json()["redacted_text"]
    except Exception as exc:
        logger.error("Presidio /redact unreachable — blocking request: %s", exc)
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail="PII screening service temporarily unavailable. Please try again shortly.",
        )


async def check_content_safety(text: str) -> tuple[bool, str]:
    """
    Checks whether text is safe (no hate speech, violence, self-harm, sexual content).
    Returns (is_safe, category_if_unsafe).

    Uses Azure AI Content Safety if configured, otherwise passes everything through.
    Like a school filter that blocks inappropriate content.
    """
    s = get_settings()

    if not s.content_safety_endpoint or not s.content_safety_key:
        return True, ""

    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.post(
                f"{s.content_safety_endpoint}/contentsafety/text:analyze?api-version=2024-02-15-preview",
                headers={
                    "Ocp-Apim-Subscription-Key": s.content_safety_key,
                    "Content-Type": "application/json",
                },
                json={"text": text[:5000]},
            )
            if resp.status_code == 200:
                data = resp.json()
                for category in data.get("categoriesAnalysis", []):
                    if category.get("severity", 0) >= 4:
                        return False, category["category"]
    except Exception as exc:
        logger.warning("Content safety check failed: %s", exc)

    return True, ""
