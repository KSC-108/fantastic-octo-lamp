FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[nse,llm]"
COPY config ./config
COPY strategy.md ./strategy.md
# Persist these paths as a volume: database, model, strategy and reports.
VOLUME ["/app/data", "/app/artifacts", "/app/reports"]
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz')"
# Secrets (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DASHBOARD_TOKEN, ANTHROPIC_API_KEY) come from the environment.
CMD ["octoquant", "--config", "config/nse.yaml", "serve", "--host", "0.0.0.0", "--port", "8000"]
