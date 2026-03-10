.PHONY: help install install-dev venv lint ruff mypy pylint format test test-unit test-e2e \
       dry-run convert replay clean clean-artifacts clean-all check

.DEFAULT_GOAL := help

PYTHON   ?= python3
VENV     := .venv
BIN      := $(VENV)/bin
PIP      := $(BIN)/pip
PYTEST   := $(BIN)/pytest
RUFF     := $(BIN)/ruff
MYPY     := $(BIN)/mypy
PYLINT   := $(BIN)/pylint

PDF       ?= raw/example1.pdf
OUTPUT    ?=
DPI       ?= 192
PROVIDER  ?= openai
MODEL     ?=
PLANG     ?= en
REASON    ?= medium
MAX_PAGES ?=
PAGES     ?=
BATCH     ?=
REPLAY    ?=
EXTRA     ?=
P2P       := $(BIN)/python -m src

help: ## Show this help (default target)
	@echo ""
	@echo "P2P — PDF to PPTX Converter"
	@echo "============================="
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Conversion variables (override with VAR=value):"
	@echo "  PDF       Input PDF path (default: raw/example1.pdf)"
	@echo "  OUTPUT   Output PPTX path (optional)"
	@echo "  PROVIDER API provider: openai | anthropic (default: openai)"
	@echo "  MODEL    Model name (override env)"
	@echo "  DPI      Render DPI: 96|144|192|288 (default: 192)"
	@echo "  PLANG    Prompt language: en|zh (default: en)"
	@echo "  REASON   Reasoning effort: low|medium|high|xhigh (default: medium)"
	@echo "  MAX_PAGES Max pages to convert (0=all)"
	@echo "  PAGES    Page spec, e.g. 0,2,5-8"
	@echo "  BATCH    Batch size (0=auto)"
	@echo "  EXTRA    Extra args passed to p2p (e.g. --use-responses-api)"
	@echo ""
	@echo "Examples:"
	@echo "  make install-dev     # Install with dev deps"
	@echo "  make dry-run         # Estimate tokens/cost"
	@echo "  make convert         # Full conversion"
	@echo "  make replay REPLAY=runs/run-xxx-yyy"
	@echo ""

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

venv: ## Create virtual environment
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	@echo "Virtual environment created at $(VENV)/"

install: venv ## Install project dependencies
	$(PIP) install -e .
	@echo "Installed p2p and runtime dependencies"

install-dev: venv ## Install project + dev dependencies
	$(PIP) install -e ".[dev]"
	@echo "Installed p2p with dev dependencies"

# ---------------------------------------------------------------------------
# Code Quality
# ---------------------------------------------------------------------------

ruff: ## Run ruff linter
	$(RUFF) check src/ tests/

mypy: ## Run mypy type checker
	$(MYPY) src/

pylint: ## Run pylint
	$(PYLINT) src/ || test $$? -le 28

format: ## Auto-format code with ruff
	$(RUFF) format src/ tests/
	$(RUFF) check --fix src/ tests/

lint: ruff mypy pylint ## Run all linters (ruff + mypy + pylint)
	@echo "All lint checks passed"

check: lint test ## Run all linters and tests

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test: ## Run all tests
	$(PYTEST) tests/ -v

test-unit: ## Run unit tests only (excludes e2e)
	$(PYTEST) tests/ -v --ignore=tests/test_e2e.py --ignore=tests/test_error_recovery.py --ignore=tests/test_continue_run.py

test-e2e: ## Run end-to-end tests only
	$(PYTEST) tests/test_e2e.py tests/test_error_recovery.py tests/test_continue_run.py -v

# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

dry-run: ## Dry-run: estimate tokens/cost without calling API
	$(P2P) $(PDF) --dry-run \
		--api-provider $(PROVIDER) \
		--dpi $(DPI) \
		--prompt-lang $(PLANG) \
		--reasoning-effort $(REASON) \
		$(if $(MAX_PAGES),--max-pages $(MAX_PAGES)) \
		$(if $(PAGES),--pages $(PAGES)) \
		$(if $(BATCH),--batch-size $(BATCH)) \
		$(EXTRA)

convert: ## Full conversion: PDF → PPTX
	$(P2P) $(PDF) \
		$(if $(OUTPUT),-o $(OUTPUT)) \
		--api-provider $(PROVIDER) \
		$(if $(MODEL),--model-name $(MODEL)) \
		--dpi $(DPI) \
		--prompt-lang $(PLANG) \
		--reasoning-effort $(REASON) \
		$(if $(MAX_PAGES),--max-pages $(MAX_PAGES)) \
		$(if $(PAGES),--pages $(PAGES)) \
		$(if $(BATCH),--batch-size $(BATCH)) \
		$(EXTRA)

replay: ## Replay a previous run/dry-run (set REPLAY=runs/run-xxx-yyy)
	@test -n "$(REPLAY)" || (echo "Usage: make replay REPLAY=runs/run-xxx-yyy" && exit 1)
	$(P2P) dummy --replay $(REPLAY) $(EXTRA)

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info src/*.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned build artifacts and caches"

clean-artifacts: ## Remove all artifact directories under runs/
	rm -rf runs/
	@echo "Cleaned artifact directories"

clean-all: clean clean-artifacts ## Remove everything (caches + artifacts)
	@echo "Full cleanup complete"
