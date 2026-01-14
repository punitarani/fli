FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install act (for running GitHub Actions locally)
RUN curl -sSL https://raw.githubusercontent.com/nektos/act/master/install.sh | bash -s -- -b /usr/local/bin

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set up workspace
WORKDIR /workspace

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock README.md ./

# Copy source for package install
COPY fli/ ./fli/

# Install dependencies
RUN uv sync --extra dev --frozen

# Copy the rest of the project
COPY . .

# Ensure the virtual environment is activated by default
ENV PATH="/workspace/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/workspace/.venv"

# Default command
CMD ["bash"]
