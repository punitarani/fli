# Makefile

# List of directories and files to format and lint
TARGETS = fli/ scripts/ tests/

# Build the docs
docs:
	poetry run mkdocs build

# Format code using ruff
format:
	poetry run ruff format $(TARGETS)

# Lint code using ruff
lint:
	poetry run ruff check $(TARGETS)

# Lint and fix code using ruff
lint-fix:
	poetry run ruff check --fix $(TARGETS)

# Run tests
test:
	poetry run pytest -vv
test-fuzz:
	poetry run pytest -vv --fuzz
test-all:
	poetry run pytest -vv --all

# Display help message by default
.DEFAULT_GOAL := help
help:
	@echo "Available commands:"
	@echo "  make format      - Format code using ruff"
	@echo "  make lint        - Lint code using ruff"
	@echo "  make lint-fix    - Lint and fix code using ruff"
	@echo "  make test        - Run tests"
# Declare the targets as phony
.PHONY: format lint check help
