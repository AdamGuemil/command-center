# Command Center : un seul processus (FastAPI + uvicorn, automatisations, et le bot Discord si CC_BOT=1).
# Expose, il exige la connexion Discord (DISCORD_CLIENT_ID/SECRET, CC_PUBLIC_URL, CC_ADMINS) :
# sans elle, il refuse de demarrer. Voir docker-compose.yml et docs/OPERATIONS.md « Héberger ».
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CC_HOST=0.0.0.0 \
    CC_PORT=8787 \
    CC_OPEN_BROWSER=0

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 1000 cc && chown -R cc /app
USER cc

EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=4)"

CMD ["python", "server.py"]
