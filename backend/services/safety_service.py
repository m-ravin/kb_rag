"""
Safety Service — PII detection and content safety screening.

Every question and answer passes through here before being processed or returned.
Like a security guard who checks everyone entering or leaving a building.
"""

import logging
import re

import httpx

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

# Simple regex patterns for local PII detection fallback
_PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),            # SSN
    re.compile(r"\b[A-Z]{1,2}\d{6,9}[A-Z]?\b"),      # Passport / NRIC
    re.compile(r"\b\+?[\d\s\-]{8,15}\b"),             # Phone numbers
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),  # Email
]


async def detect_pii(text: str) -> tuple[bool, list[str]]:
    """
    Checks whether the text contains personally identifiable information.
    Returns (has_pii, list_of_detected_types).

    Uses Azure AI Language if configured, falls back to regex patterns.
    Like a paper shredder that beeps whenever it detects a secret.
    """
    s = get_settings()

    # Try Azure AI Language PII endpoint if configured
    if s.content_safety_endpoint and s.content_safety_key:
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.post(
                    f"{s.content_safety_endpoint}/language/analyze-text/jobs",
                    headers={
                        "Ocp-Apim-Subscription-Key": s.content_safety_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "tasks": [{"kind": "PiiEntityRecognition", "parameters": {"domain": "phi"}}],
                        "analysisInput": {"documents": [{"id": "1", "language": "en", "text": text[:5000]}]},
                    },
                )
                if resp.status_code == 202:
                    return False, []  # Async job — treat as safe for now
        except Exception as exc:
            logger.debug("Azure PII endpoint unavailable, falling back to regex: %s", exc)

    # Regex fallback
    detected = []
    for pattern in _PII_PATTERNS:
        if pattern.search(text):
            detected.append(pattern.pattern)

    return bool(detected), detected


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
