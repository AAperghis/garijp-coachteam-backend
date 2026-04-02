# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency file and install
COPY pyproject.toml ./
ENV UV_SYSTEM_PYTHON=1
RUN uv pip install -r pyproject.toml

# Copy source code
COPY src/ ./src/

# Set PYTHONPATH to include the src directory
ENV PYTHONPATH=/app/src

# Default command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
