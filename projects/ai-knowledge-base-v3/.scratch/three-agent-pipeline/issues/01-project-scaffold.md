Status: needs-triage

# Project scaffold: config + dependencies

## What to build

Set up the project skeleton so that `pip install -e .` works, environment variables are documented, and all code can import a unified config. This creates the foundation every other slice depends on.

End-to-end behavior: a developer runs `pip install -e .` and `python -c "from src.config import load_config; c = load_config(); print(c.log_level)"` works.

## Acceptance criteria

- [ ] `pyproject.toml` with Python 3.12, dependencies (langgraph, openclaw, python-dotenv, requests, pyyaml), and dev dependencies (pytest, ruff/mypy)
- [ ] `.env.example` listing all required env vars with descriptions (AI API keys, bot tokens, log level)
- [ ] `src/config.py` loads `.env` via python-dotenv, exposes typed config object (log_level, AI model URL, API keys, collector/analyzer/organizer settings)
- [ ] `src/__init__.py` exists (can be empty)
- [ ] `src/collector/__init__.py`, `src/analyzer/__init__.py`, `src/storage/__init__.py`, `src/distributor/__init__.py` exist
- [ ] Basic logging configured in `config.py` — all future modules can do `logger = logging.getLogger(__name__)`
- [ ] `pip install -e .` succeeds with no errors

## Blocked by

None - can start immediately
