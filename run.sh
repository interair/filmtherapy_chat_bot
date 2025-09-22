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

# Choose Python interpreter: prefer 3.11 to avoid building incompatible C-extensions on 3.13
choose_python() {
  if command -v python3.11 >/dev/null 2>&1; then
    echo "python3.11"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi
  echo "" # none found
}

PY=$(choose_python)
if [ -z "$PY" ]; then
  echo "No Python interpreter found. Please install Python 3.11 or Docker." >&2
  exit 1
fi

# Check version and prefer Docker if running on Python >= 3.13 without 3.11 available
PYVER=$($PY -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
if [ "$PYVER" != "3.11" ] && [ "$PYVER" \> "3.12" ]; then
  # Try to fallback to Docker
  if command -v docker >/dev/null 2>&1; then
    echo "Detected Python $PYVER. Building and running Docker image to avoid local build issues..." >&2
    docker build -t gantich-chat-bot:dev .
    # Pass .env if present
    DOCKER_ENV=()
    if [ -f .env ]; then
      DOCKER_ENV+=(--env-file ./.env)
    fi
    exec docker run --rm \
      -e IN_DOCKER=1 \
      -v "$(pwd)/logs:/app/logs" \
      "${DOCKER_ENV[@]}" \
      gantich-chat-bot:dev
  else
    echo "Python $PYVER detected and Docker not available. Please install Python 3.11 to run locally" >&2
    exit 1
  fi
fi

# Create venv if missing or if created with a different Python minor version
VENV_PY=".venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  $PY -m venv .venv
else
  VENV_VER=$($VENV_PY -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
  if [ "$VENV_VER" != "$PYVER" ]; then
    echo "Recreating virtualenv with Python $PYVER (was $VENV_VER)..."
    rm -rf .venv
    $PY -m venv .venv
  fi
fi

# Activate venv
source .venv/bin/activate

# Install deps only when requirements changed
REQ_HASH_FILE=".venv/.requirements.hash"
# Compute SHA-256 cross-platform (linux/macos)
hash_requirements() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum requirements.txt | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 requirements.txt | awk '{print $1}'
  else
    # Fallback to Python
    "$PY" - <<'PY'
import hashlib, sys
with open('requirements.txt','rb') as f:
    print(hashlib.sha256(f.read()).hexdigest())
PY
  fi
}
NEW_HASH=$(hash_requirements)
OLD_HASH=""
if [ -f "$REQ_HASH_FILE" ]; then
  OLD_HASH=$(cat "$REQ_HASH_FILE" || true)
fi
if [ "$NEW_HASH" != "$OLD_HASH" ]; then
  echo "Installing/updating dependencies..."
  pip install -r requirements.txt
  echo -n "$NEW_HASH" > "$REQ_HASH_FILE"
else
  echo "Dependencies up-to-date. Skipping install."
fi

# Run bot
exec python -m src.main
