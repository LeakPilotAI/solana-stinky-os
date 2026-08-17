FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy core first (local path dependency)
COPY packages/stinky-core /packages/stinky-core
COPY services/event-log /app

RUN pip install --no-cache-dir -e /packages/stinky-core \
    && pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000 9100

CMD ["uvicorn", "event_log.api:app", "--host", "0.0.0.0", "--port", "8000"]
