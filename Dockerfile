# Production Dockerfile for Fli MCP Server
# Build: docker build -t fli-mcp .
# Run:   docker run -d -p 8000:8000 fli-mcp
#
# Note: This is separate from .devcontainer/Dockerfile which is for development.
# The devcontainer includes dev tools (git, make, act) and dev dependencies,
# resulting in a larger image (~500MB+). This production Dockerfile creates a
# minimal image (~350MB) with only runtime dependencies needed to run the MCP server.

FROM python:3.10-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock README.md ./

# Copy source code
COPY fli/ ./fli/

# Install production dependencies only (no dev extras)
RUN uv sync --frozen --no-dev

# Add virtual environment to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Configure server to bind to all interfaces
ENV HOST=0.0.0.0
ENV PORT=8000

# Expose the MCP HTTP server port
EXPOSE 8000

# Run the MCP HTTP server
CMD ["fli-mcp-http"]
