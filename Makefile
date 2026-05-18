.PHONY: install test lint format typecheck up down run-dashboard write-demo-dashboard

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
	streamlit run scripts/dashboard.py

write-demo-dashboard:
	python3 scripts/write_demo_dashboard_status.py
