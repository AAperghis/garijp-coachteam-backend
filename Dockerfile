# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv
ENV UV_VERSION=0.1.0
RUN pip install --no-cache-dir "uv==$UV_VERSION"

# Copy dependency file and install
COPY pyproject.toml ./
RUN uv config virtualenvs.create false \
    && uv pip install --group main

# Copy source code
COPY src/ ./src/

# Set PYTHONPATH to include the src directory
ENV PYTHONPATH=/app/src

# Default command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
