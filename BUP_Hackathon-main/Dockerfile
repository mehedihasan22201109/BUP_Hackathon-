# GridWise - LLM-Assisted Energy Optimizer
# Slim runtime image based on python:3.11-slim
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 `
    PYTHONUNBUFFERED=1 `
    PIP_NO_CACHE_DIR=1 `
    PIP_DISABLE_PIP_VERSION_CHECK=1 `
    HOST=0.0.0.0 `
    PORT=8000

WORKDIR /app

# System deps (certificates only; PuLP ships with bundled CBC solver)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY sample_cases ./sample_cases
COPY README.md ./README.md

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3); sys.exit(0 if r.status==200 else 1)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
