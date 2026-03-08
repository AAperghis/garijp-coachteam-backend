# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install Poetry
ENV POETRY_VERSION=1.8.2
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

# Copy dependency files and install
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-root --only main

# Copy source code
COPY src/ ./src/

# Set PYTHONPATH to include the src directory
ENV PYTHONPATH=/app/src

# Default command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
