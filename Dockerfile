FROM python:3.12-slim-bookworm

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files (README.md is referenced as the package readme in pyproject.toml)
COPY pyproject.toml uv.lock README.md ./

# Install python dependencies in virtual environment
RUN uv sync --frozen --no-dev

# Copy application source code
COPY src/ src/
COPY db/ db/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uvicorn", "src.service.api:app", "--host", "0.0.0.0", "--port", "8080"]
