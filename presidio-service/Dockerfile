# ── Build stage: install Python deps with uv ──────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

WORKDIR /app

# Install Python deps into a virtual environment
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

RUN uv pip install --no-cache \
    "fastapi>=0.112.0" \
    "uvicorn[standard]>=0.30.6" \
    "presidio-analyzer>=2.2.355" \
    "presidio-anonymizer>=2.2.355" \
    "spacy>=3.7.0"

# Download the spaCy language model used by Presidio.
# en_core_web_lg gives better accuracy than en_core_web_sm (~500 MB, baked into the image).
RUN python -m spacy download en_core_web_lg

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY main.py .

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Two workers — spaCy model is loaded per-worker, so keep low to save memory.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
