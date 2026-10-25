# Ollama Signal Bot — common tasks.
# Run `make` (or `make help`) to list available targets.

SHELL := /bin/bash
COMPOSE := docker compose
PROFILE ?=
PROFILE_FLAGS := $(if $(PROFILE),--profile $(PROFILE),)
MODEL ?= gemma4:latest

.DEFAULT_GOAL := help

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Run the interactive installer
	python3 setup.py

dev: ## Create a venv and install dependencies
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt -r requirements-dev.txt

test: ## Run the test suite
	.venv/bin/pytest -q

build: ## Build the bot image
	$(COMPOSE) build

up: ## Start the stack (add PROFILE=ollama to include bundled Ollama)
	$(COMPOSE) $(PROFILE_FLAGS) up -d

down: ## Stop the stack (add PROFILE=ollama to stop bundled Ollama too)
	$(COMPOSE) $(PROFILE_FLAGS) down

restart: ## Restart the bot
	$(COMPOSE) restart ollama-signal-bot

logs: ## Follow the bot's logs
	$(COMPOSE) logs -f ollama-signal-bot

model-pull: ## Pull a model into bundled Ollama (MODEL=... to override)
	$(COMPOSE) --profile ollama exec ollama ollama pull $(MODEL)

ps: ## Show container status and health
	$(COMPOSE) ps

clean: ## Stop everything and remove volumes (destructive)
	$(COMPOSE) down -v

.PHONY: help setup dev test build up down restart logs model-pull ps clean
