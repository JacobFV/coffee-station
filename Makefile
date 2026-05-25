PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
PIP_INSTALL ?= $(BIN)/pip install --retries 5 --timeout 120

.PHONY: help venv install dev test run clean

help:
	@echo "Targets:"
	@echo "  install         Create venv and install package with dev tools and LeRobot"
	@echo "  test            Run pytest"
	@echo "  run             Run coffee-station"
	@echo "  clean           Remove venv and caches"

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(PIP_INSTALL) --upgrade pip

venv: $(BIN)/python

install: venv
	$(PIP_INSTALL) -e ".[dev]"

dev: install

test:
	$(BIN)/pytest

run:
	$(BIN)/coffee-station

clean:
	rm -rf $(VENV) .pytest_cache **/__pycache__ src/*.egg-info
