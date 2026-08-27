FROM python:3.11-slim

WORKDIR /app

COPY services/orbital /app/services/orbital
COPY services/api /app/services/api
COPY contracts /app/contracts

RUN pip install --no-cache-dir -e /app/services/orbital -e /app/services/api

WORKDIR /app/services/api

EXPOSE 8000

CMD ["uvicorn", "prahari_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
