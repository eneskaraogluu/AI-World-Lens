FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY --chown=10001:10001 . .
RUN mkdir -p /app/data /app/frontend/assets/generations \
    && chown -R 10001:10001 /app

USER 10001:10001

EXPOSE 8000

CMD ["sh", "-c", "python scripts/docker_bootstrap.py && exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
