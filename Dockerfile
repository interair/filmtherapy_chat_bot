FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH="/app" \
    PYTHONNOUSERSITE=1 \
    APP_PROFILE_STARTUP=1

# Create user and workdir in one layer
RUN useradd -m -u 10001 appuser && mkdir -p /app
WORKDIR /app

# Install dependencies with optimizations
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --prefer-binary -r requirements.txt \
    && LIB="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
    && STDLIB="$(python -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])')" \
    && python -m compileall -q -o 1 "$LIB" \
    && python -m compileall -q -o 1 "$STDLIB" \
    && find "$LIB" -name "tests" -type d -exec rm -rf {} + 2>/dev/null || true

# Copy source and early logging helper
COPY src ./src
COPY sitecustomize.py ./

# Compile everything and set permissions in one layer
RUN python -m compileall -q -o 1 /app/src /app/sitecustomize.py \
    && mkdir -p logs data \
    && chown -R appuser:appuser /app

USER appuser

CMD ["python", "-m", "src.main"]
