#!/usr/bin/env bash
set -euo pipefail

# Simple runner for local development and Docker
# Usage:
#   cp .env.example .env
#   edit .env to set TELEGRAM_TOKEN and optional ADMINS
#   ./run.sh

# Detect Docker runtime: /.dockerenv exists in Docker containers
if [ -f /.dockerenv ] || [ "${IN_DOCKER:-}" = "1" ]; then
  # In Docker: environment variables are already provided, dependencies installed at build
  exec python -m src.main
fi

# Also detect Cloud Run / managed container platforms (K_SERVICE is set by Cloud Run)
if [ -n "${K_SERVICE:-}" ]; then
  exec python -m src.main
fi

# If not in a container:
# - proceed if TELEGRAM_TOKEN is already set in the environment (no .env needed)
# - otherwise, require .env for local development
if [ -z "${TELEGRAM_TOKEN:-}" ] && [ ! -f .env ]; then
  echo ".env not found. Create it from .env.example and set TELEGRAM_TOKEN" >&2
  exit 1
fi

# Create venv if missing
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Install deps if needed
pip install -r requirements.txt

# Run bot
exec python -m src.main
