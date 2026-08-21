FROM python:3.11-slim AS runtime
WORKDIR /app

# Install dependencies first (cached layer — only re-runs when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Non-root user created before COPY so chown is cheap
RUN useradd -m -u 1001 masova && chown /app -R masova
USER masova

# Copy only application source (not tests/docs)
COPY --chown=masova:masova src/ src/

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1

EXPOSE 8000
CMD ["uvicorn", "src.masova_agent.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
