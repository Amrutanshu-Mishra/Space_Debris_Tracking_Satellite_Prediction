FROM python:3.11-slim

WORKDIR /app

COPY services/orbital /app/services/orbital
COPY services/worker /app/services/worker
COPY contracts /app/contracts

RUN pip install --no-cache-dir -e /app/services/orbital -e /app/services/worker

WORKDIR /app/services/worker

CMD ["celery", "-A", "prahari_worker.celery_app", "worker", "--beat", "--loglevel=INFO"]
