# Makefile

# List of directories and files to format and lint
TARGETS = fli/ scripts/ tests/

# Run the server
server:
	poetry run uvicorn fli.server.main:app
server-dev:
	poetry run uvicorn fli.server.main:app --reload

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

# Generate the requirements.txt file
requirements:
	poetry export --without-hashes --without-urls --format requirements.txt > requirements.txt
	sed -e 's/ ;.*//' requirements.txt > requirements.tmp && mv requirements.tmp requirements.txt

# Display help message by default
.DEFAULT_GOAL := help
help:
	@echo "Available commands:"
	@echo "  make server      - Run the server"
	@echo "  make format      - Format code using ruff"
	@echo "  make lint        - Lint code using ruff"
	@echo "  make lint-fix    - Lint and fix code using ruff"
	@echo "  make test        - Run tests"
	@echo "  make test-fuzz   - Run tests with fuzzing"
	@echo "  make test-all    - Run all tests"
	@echo "  make requirements - Generate the requirements.txt file"
# Declare the targets as phony
.PHONY: format lint check help
