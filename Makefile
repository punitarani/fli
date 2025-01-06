# Makefile

# List of directories and files to format and lint
TARGETS = fli/ scripts/ tests/

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

# Run the app
run:
	poetry run streamlit run app.py

# Display help message by default
.DEFAULT_GOAL := help
help:
	@echo "Available commands:"
	@echo "  make format      - Format code using ruff"
	@echo "  make lint        - Lint code using ruff"
	@echo "  make lint-fix    - Lint and fix code using ruff"
	@echo "  make test        - Run tests"
	@echo "  make run         - Run the app"
# Declare the targets as phony
.PHONY: format lint check help
