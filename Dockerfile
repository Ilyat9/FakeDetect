# --- Stage 1: build dependencies into an isolated venv -----------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# --- Stage 2: runtime image ----------------------------------------------------
FROM python:3.12-slim

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Chromium system dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

COPY main.py server.py index.html ./
COPY core/ core/
COPY routers/ routers/
COPY services/ services/
COPY parsers/ parsers/
COPY database.py llm_provider.py aggregator.py batch_processor.py telegram_alerts.py ./

# Download Chromium browser into the image (deep analysis / batch screenshots)
RUN playwright install --with-deps chromium

# Non-root user
RUN useradd --create-home appuser && chown -R appuser /app /home/appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fs http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
