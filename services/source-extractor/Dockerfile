FROM python:3.12.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8090 \
    EXTRACTOR_MAX_RESPONSE_BYTES=20971520 \
    EXTRACTOR_MAX_NORMALIZED_BYTES=10485760 \
    EXTRACTOR_MAX_RAW_CAPTURE_BYTES=8388608

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/source-extractor
COPY vendor/source-extractor/ ./
RUN test -f pyproject.toml \
    && python -m pip install --upgrade pip==25.2 \
    && python -m pip install . 'PyPDF2==3.0.1' \
    && apt-get purge -y --auto-remove gcc libxml2-dev libxslt1-dev \
    && rm -rf /root/.cache

WORKDIR /app
COPY services/source-extractor/app/ ./

RUN groupadd --system extractor \
    && useradd --system --gid extractor --no-create-home --home-dir /nonexistent extractor \
    && chown -R extractor:extractor /app

USER extractor
EXPOSE 8090
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=4 \
  CMD ["python", "-c", "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8090/health/ready', timeout=2))['status'] == 'ready'"]

CMD ["python", "-m", "adapter"]
