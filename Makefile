.PHONY: help install test scan ingest serve watch clean

VENV := .venv
PYTHON := $(VENV)/bin/python
UVICORN := $(VENV)/bin/uvicorn
PYTEST := $(VENV)/bin/pytest

help:
	@echo "Brain LLM Archive Management:"
	@echo "  make install  - Install dependencies using uv"
	@echo "  make test     - Run test suite"
	@echo "  make scan     - Discover local Antigravity & Claude Code sessions"
	@echo "  make ingest   - Normalize discovered sessions to doc/llm-archive/*.md"
	@echo "  make serve    - Run FastAPI backend on port 8080"
	@echo "  make extract-takeout - Extract ZIP/TAR archives in takeout directory"
	@echo "  make import-takeout  - Bulk import & reconcile Takeout dumps into Postgres & Markdown"

install:
	uv venv $(VENV)
	uv pip install -e . --python $(PYTHON)

test:
	$(PYTEST) tests -v

scan:
	$(PYTHON) -m src.cli.main scan

ingest:
	$(PYTHON) -m src.cli.main ingest

serve:
	$(PYTHON) -m src.cli.main serve

watch:
	$(PYTHON) -m src.cli.main watch

extract-takeout:
	$(PYTHON) -m src.cli.main extract-takeout $(ARGS)

import-takeout:
	$(PYTHON) -m src.cli.main import-takeout $(ARGS)

sync-s3:
	$(PYTHON) -m src.cli.main sync-s3 $(ARGS)

web-install:
	cd web && pnpm install

web-build:
	cd web && pnpm run build

web-check:
	cd web && pnpm run check


daemon-install:
	$(MAKE) -C daemon install

daemon-start:
	$(MAKE) -C daemon start

daemon-stop:
	$(MAKE) -C daemon stop

daemon-restart:
	$(MAKE) -C daemon restart

daemon-status:
	$(MAKE) -C daemon status

daemon-logs:
	$(MAKE) -C daemon logs

clean:
	rm -rf $(VENV) .pytest_cache

