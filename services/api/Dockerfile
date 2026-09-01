# 3.13 to match the dev environment (services/orbital/requirements.txt is a
# 3.13 freeze). numpy, scipy, asyncpg, uvloop, httptools and watchfiles all
# publish cp313 manylinux wheels, so `pip install` stays wheels-only and this
# slim image needs no C toolchain.
FROM python:3.13-slim

WORKDIR /app

COPY services/orbital /app/services/orbital
COPY services/api /app/services/api
COPY contracts /app/contracts

RUN pip install --no-cache-dir -e /app/services/orbital -e /app/services/api

WORKDIR /app/services/api

EXPOSE 8000

CMD ["uvicorn", "prahari_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
