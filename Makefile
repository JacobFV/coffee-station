PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help venv install install-lerobot dev test run clean

help:
	@echo "Targets:"
	@echo "  install         Create venv and install package with dev extras"
	@echo "  install-lerobot Install lerobot extra into the venv"
	@echo "  test            Run pytest"
	@echo "  run             Run coffee-station"
	@echo "  clean           Remove venv and caches"

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

venv: $(BIN)/python

install: venv
	$(BIN)/pip install -e ".[dev]"

install-lerobot: venv
	$(BIN)/pip install -e ".[lerobot]"

dev: install

test:
	$(BIN)/pytest

run:
	$(BIN)/coffee-station

clean:
	rm -rf $(VENV) .pytest_cache **/__pycache__ src/*.egg-info
