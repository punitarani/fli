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

# Run the MCP server
mcp:
	uv run fli-mcp

# Run the MCP server over HTTP
mcp-http:
	uv run fli-mcp-http

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

# Run CI locally using act (requires Docker and act: https://github.com/nektos/act)
ci:
	act -j lint -j test --workflows .github/workflows/test.yml

# Run CI in Docker container (mounts source and Docker socket for act)
ci-docker:
	docker run --rm \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-v $(PWD):/workspace \
		-w /workspace \
		fli-dev make ci

# Build dev container
devcontainer:
	docker build -t fli-dev -f .devcontainer/Dockerfile .

# Generate the requirements.txt file
requirements:
	uv export --format requirements-txt --no-hashes > requirements.txt

# Preview next versions for each bump kind (does not modify files)
bump-preview:
	@python scripts/bump_version.py --bump patch
	@echo "---"
	@python scripts/bump_version.py --bump minor
	@echo "---"
	@python scripts/bump_version.py --bump major

# Preview release notes since the last tag (or last "Bump version" commit)
release-notes:
	@prev=$$(git tag --list 'v*' --sort=-v:refname | head -n1); \
	if [ -z "$$prev" ]; then \
		prev=$$(git log --grep='^Bump version' -n1 --format='%H'); \
	fi; \
	if [ -z "$$prev" ]; then \
		echo "(no previous tag found, showing full history)"; \
		git log --pretty=format:'- %s (%h)' HEAD; \
	else \
		echo "Commits since $$prev:"; \
		git log --pretty=format:'- %s (%h)' "$$prev..HEAD"; \
	fi
	@echo

# Display help message by default
.DEFAULT_GOAL := help
help:
	@echo "Available commands:"
	@echo "  make install     - Install dependencies"
	@echo "  make install-dev - Install with dev dependencies"
	@echo "  make install-all - Install all dependencies"
	@echo "  make mcp         - Run the MCP server"
	@echo "  make docs        - Build the docs"
	@echo "  make format      - Format code using ruff"
	@echo "  make lint        - Lint code using ruff"
	@echo "  make lint-fix    - Lint and fix code using ruff"
	@echo "  make test        - Run tests"
	@echo "  make test-mcp    - Run tests with MCP"
	@echo "  make test-fuzz   - Run tests with fuzzing"
	@echo "  make test-all    - Run all tests"
	@echo "  make ci          - Run CI locally using act (requires Docker)"
	@echo "  make ci-docker   - Run CI in Docker container"
	@echo "  make devcontainer - Build dev container image"
	@echo "  make requirements - Generate the requirements.txt file"
	@echo "  make bump-preview - Preview next version (patch/minor/major)"
	@echo "  make release-notes - Preview release notes since last tag"
# Declare the targets as phony
.PHONY: help install install-dev install-all mcp mcp-http docs format lint lint-fix test test-mcp test-fuzz test-all ci ci-docker devcontainer requirements bump-preview release-notes
