# Spoken interview practice. `make` on its own lists what you can do.
.DEFAULT_GOAL := help
.PHONY: help install models run check fmt build up down restart logs shell clean reset

PY      ?= ./.venv/bin/python
COMPOSE ?= docker compose
KOKORO  := https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0

help:  ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

# ---- native ----

install:  ## Install Python dependencies into .venv
	uv pip install -e .

models:  ## Download the Kokoro voice weights (~340MB, once)
	@mkdir -p models
	@if [ -f kokoro-v1.0.onnx ] && [ ! -f models/kokoro-v1.0.onnx ]; then \
		echo "  moving existing weights into models/"; \
		mv kokoro-v1.0.onnx voices-v1.0.bin models/ 2>/dev/null || true; fi
	@test -f models/kokoro-v1.0.onnx || \
		(echo "  kokoro-v1.0.onnx (310MB)..." && curl -fL# -o models/kokoro-v1.0.onnx $(KOKORO)/kokoro-v1.0.onnx)
	@test -f models/voices-v1.0.bin || \
		(echo "  voices-v1.0.bin (27MB)..." && curl -fL# -o models/voices-v1.0.bin $(KOKORO)/voices-v1.0.bin)
	@echo "  ready"

run: models  ## Run the app natively (fastest on a Mac)
	$(PY) main.py

check:  ## ruff, formatter, line budget and tests
	./scripts/check.sh

fmt:  ## Reformat and autofix what ruff can
	ruff check . --fix && ruff format .

# ---- docker ----

build:  ## Build the container image
	$(COMPOSE) build

up: models  ## Start the stack in the background
	@mkdir -p data
	$(COMPOSE) up -d
	@echo "  http://127.0.0.1:$${PORT:-8000}  (first start loads Whisper, give it a minute)"

down:  ## Stop the stack
	$(COMPOSE) down

restart: down up  ## Restart the stack

logs:  ## Follow the container logs
	$(COMPOSE) logs -f

shell:  ## Open a shell inside the running container
	$(COMPOSE) exec coach bash

# ---- housekeeping ----

clean:  ## Remove caches and build artefacts (keeps your practice data)
	rm -rf .ruff_cache **/__pycache__ src/**/__pycache__ *.egg-info build dist

reset:  ## Delete every session, metric and recording. Not reversible.
	@printf "  Delete all practice data? [y/N] " && read a && [ "$$a" = "y" ]
	rm -rf data practice.db recordings
	@echo "  gone"
