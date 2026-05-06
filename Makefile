.PHONY: install test lint format typecheck up down run-dashboard

install:
	pip install -e ".[dev]"

test:
	pytest

test-cov:
	pytest --cov=trading_engine --cov-report=term-missing

lint:
	ruff check src tests

format:
	ruff format src tests

typecheck:
	mypy src

up:
	docker compose up -d

down:
	docker compose down

run-dashboard:
	@echo "Dashboard not implemented yet (Milestone 10)."
	@echo "Run: streamlit run src/trading_engine/dashboard/app.py"
