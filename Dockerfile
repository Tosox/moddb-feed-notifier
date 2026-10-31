FROM python:3.15-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MFN_STATE_DIR=/app/state

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . \
 && useradd --system --uid 1000 notifier \
 && mkdir -p /app/state \
 && chown notifier /app/state

USER notifier
CMD ["moddb-feed-notifier"]
