FROM python:3.13.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN groupadd --system stormcloud && useradd --system --gid stormcloud --create-home stormcloud
WORKDIR /app
COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY config ./config
RUN python -m pip install --upgrade pip==25.2 && python -m pip install .
USER stormcloud
EXPOSE 8080 8085 8090
CMD ["uvicorn", "stormcloud.main:app", "--host", "0.0.0.0", "--port", "8080"]
