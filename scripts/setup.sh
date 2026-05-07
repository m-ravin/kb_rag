#!/bin/bash
# ── Quick-start setup script ──────────────────────────────────────────────────
# Run this once after cloning to set up the local development environment.
# Requires: az CLI, terraform, kubectl, uv, node (v20+)

set -euo pipefail

echo "=== kb-rag RAG — Local Setup ==="

# 1. Copy environment template
if [ ! -f .env ]; then
  cp .env.example .env
  echo "[1/5] Created .env from .env.example — FILL IN YOUR AZURE CREDENTIALS"
else
  echo "[1/5] .env already exists, skipping"
fi

# 2. Install Python dependencies
echo "[2/5] Installing Python dependencies with uv..."
uv sync

# 3. Install frontend dependencies
echo "[3/5] Installing frontend dependencies..."
cd frontend && npm install && cd ..

# 4. Initialise Terraform
echo "[4/5] Initialising Terraform..."
cd infrastructure/terraform && terraform init && cd ../..

echo "[5/5] Done!"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your Azure credentials"
echo "  2. Run 'docker-compose up' for local dev"
echo "  3. Run 'cd infrastructure/terraform && terraform apply' to provision Azure resources"
echo "  4. Run 'uv run uvicorn backend.main:app --reload' for backend dev"
echo "  5. Run 'cd frontend && npm run dev' for frontend dev"
