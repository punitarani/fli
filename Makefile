# Makefile

# List of directories and files to format and lint
TARGETS = fli/ scripts/ tests/

# Install dependencies
install:
	uv sync

install-dev:
	uv sync --extra dev

install-all:
	uv sync --extra dev

# Run the server
server:
	uv run uvicorn fli.server.main:app
server-dev:
	uv run uvicorn fli.server.main:app --reload

# Run the MCP server
mcp:
	uv run fli-mcp

# Build the docs
docs:
	uv run --extra dev mkdocs build

# Format code using ruff
format:
	uv run --extra dev ruff format $(TARGETS)

# Lint code using ruff
lint:
	uv run --extra dev ruff check $(TARGETS)

# Lint and fix code using ruff
lint-fix:
	uv run --extra dev ruff check --fix $(TARGETS)

# Run tests
test:
	uv run --extra dev pytest -vv
test-mcp:
	uv run --extra dev pytest -vv --mcp
test-fuzz:
	uv run --extra dev pytest -vv --fuzz
test-all:
	uv run --extra dev pytest -vv --all

# Generate the requirements.txt file
requirements:
	uv export --format requirements-txt --no-hashes > requirements.txt
# Display help message by default
.DEFAULT_GOAL := help
help:
	@echo "Available commands:"
	@echo "  make install     - Install dependencies"
	@echo "  make install-dev - Install with dev dependencies"
	@echo "  make install-all - Install all dependencies"
	@echo "  make server      - Run the server"
	@echo "  make server-dev  - Run the development server with reload"
	@echo "  make mcp         - Run the MCP server"
	@echo "  make docs        - Build the docs"
	@echo "  make format      - Format code using ruff"
	@echo "  make lint        - Lint code using ruff"
	@echo "  make lint-fix    - Lint and fix code using ruff"
	@echo "  make test        - Run tests"
	@echo "  make test-mcp    - Run tests with MCP"
	@echo "  make test-fuzz   - Run tests with fuzzing"
	@echo "  make test-all    - Run all tests"
	@echo "  make requirements - Generate the requirements.txt file"
# Declare the targets as phony
.PHONY: help install install-dev install-all server server-dev mcp docs format lint lint-fix test test-mcp test-fuzz test-all requirements
