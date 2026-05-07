"""
Monitoring Service — logs every Q&A interaction for reporting.

Every question asked and answer given is saved here so we can later
analyse: how many questions per day, which topics are most common,
how many times PII was detected, how fast the system responds, etc.
"""

import logging
from datetime import datetime, timezone

from backend.core.clients import get_db

logger = logging.getLogger(__name__)


async def log_qa_interaction(
    session_id: str,
    question: str,
    answer: str,
    question_type: str,
    sources: list[dict],
    tokens_used: int,
    latency_ms: float,
    flagged_pii: bool,
    flagged_unsafe: bool,
    language: str,
) -> None:
    """
    Saves one complete Q&A interaction to Cosmos MongoDB.
    This data feeds the reporting pipeline and Power BI dashboard.
    """
    try:
        db = get_db()
        await db["qa_logs"].insert_one(
            {
                "session_id": session_id,
                "question": question,
                "answer": answer,
                "question_type": question_type,
                "source_count": len(sources),
                "tokens_used": tokens_used,
                "latency_ms": latency_ms,
                "flagged_pii": flagged_pii,
                "flagged_unsafe": flagged_unsafe,
                "language": language,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as exc:
        # Logging failure must never break the user-facing response
        logger.warning("Failed to log Q&A interaction: %s", exc)


async def get_metrics_summary() -> dict:
    """
    Aggregates Q&A log data for the monitoring dashboard.
    Returns counts of interactions, PII flags, average latency, etc.
    """
    db = get_db()
    pipeline = [
        {
            "$group": {
                "_id": None,
                "total_questions": {"$sum": 1},
                "avg_latency_ms": {"$avg": "$latency_ms"},
                "total_tokens": {"$sum": "$tokens_used"},
                "pii_flagged_count": {"$sum": {"$cond": ["$flagged_pii", 1, 0]}},
                "unsafe_flagged_count": {"$sum": {"$cond": ["$flagged_unsafe", 1, 0]}},
            }
        }
    ]
    result = await db["qa_logs"].aggregate(pipeline).to_list(1)
    return result[0] if result else {
        "total_questions": 0,
        "avg_latency_ms": 0,
        "total_tokens": 0,
        "pii_flagged_count": 0,
        "unsafe_flagged_count": 0,
    }
