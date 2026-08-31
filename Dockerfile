FROM python:3.11-slim AS runtime
WORKDIR /app

# Install dependencies first (cached layer — only re-runs when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Non-root user + writable data dirs created before COPY so chown is cheap
RUN useradd -m -u 1001 masova \
    && mkdir -p data/demo data/proposals data/runs \
    && chown -R masova:masova /app
USER masova

COPY --chown=masova:masova src/ src/
COPY --chown=masova:masova scripts/seed_demo_data.py scripts/seed_demo_data.py
COPY --chown=masova:masova scripts/__init__.py scripts/__init__.py
COPY --chown=masova:masova data/knowledge/ data/knowledge/

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('PORT','8080') + '/health').read()" || exit 1

EXPOSE 8080
CMD ["sh", "-c", "uvicorn src.masova_agent.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
