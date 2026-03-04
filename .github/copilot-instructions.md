# Copilot Instructions

## Python Environment

- Always use the project virtual environment at `.venv`.
- If it does not exist, create it first:
  - `python3 -m venv .venv`
- Activate before running Python tooling:
  - `source .venv/bin/activate`

## Dependency Installation

- Install dependencies inside `.venv` only:
  - `pip install -r requirements.txt`
  - `pip install -r requirements-dev.txt`

## Running Commands

- Prefer virtual environment binaries explicitly:
  - `.venv/bin/python -m src.main`
  - `PYTHONPATH=. .venv/bin/pytest -q`
  - `.venv/bin/pip list`
