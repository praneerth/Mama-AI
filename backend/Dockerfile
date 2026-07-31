# syntax=docker/dockerfile:1.7

FROM python:3.14-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt ./requirements-prod.txt
RUN python -m pip install --upgrade pip wheel \
    && python -m pip wheel --wheel-dir /wheels --requirement requirements-prod.txt

FROM python:3.14-slim-bookworm AS runtime

ARG MAMA_UID=10001
ARG MAMA_GID=10001

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000

RUN groupadd --gid "${MAMA_GID}" mama-ai \
    && useradd --uid "${MAMA_UID}" --gid "${MAMA_GID}" --create-home --shell /usr/sbin/nologin mama-ai

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements-prod.txt ./requirements-prod.txt
RUN python -m pip install --no-index --find-links=/wheels --requirement requirements-prod.txt \
    && rm -rf /wheels

COPY . /app

RUN mkdir -p \
      /var/lib/mama-ai/data \
      /var/lib/mama-ai/database \
      /var/lib/mama-ai/backups \
      /var/lib/mama-ai/screenshots \
      /var/lib/mama-ai/models \
      /var/log/mama-ai \
      /var/cache/mama-ai \
      /tmp/mama-ai \
    && chown -R mama-ai:mama-ai \
      /app \
      /var/lib/mama-ai \
      /var/log/mama-ai \
      /var/cache/mama-ai \
      /tmp/mama-ai

USER mama-ai

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-m", "app.deployment.healthcheck"]

CMD ["python", "-m", "app.deployment.launcher"]
