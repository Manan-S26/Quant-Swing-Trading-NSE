.PHONY: install test test-cov test-safety lint format typecheck up down \
        run-dashboard write-demo-dashboard live-preflight live-dry-run

install:
	pip install -e ".[dev]"

test:
	pytest

test-cov:
	pytest --cov=trading_engine --cov-report=term-missing

# Run only the live execution and script safety tests
test-safety:
	pytest tests/unit/live_execution/ tests/unit/scripts/ -v

lint:
	ruff check src tests scripts

format:
	ruff format src tests scripts

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

# Run preflight checks (does not place orders, does not require credentials)
live-preflight:
	python3 scripts/live_pilot_preflight.py

# Run a dry-run order preview (does not place orders, does not require credentials)
live-dry-run:
	python3 scripts/live_order_dry_run.py \
		--symbol RELIANCE \
		--side BUY \
		--quantity 1 \
		--order-type MARKET
