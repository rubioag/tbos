FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir -e ".[dev]"

CMD ["uvicorn", "tbos.main:app", "--host", "0.0.0.0", "--port", "8000"]
