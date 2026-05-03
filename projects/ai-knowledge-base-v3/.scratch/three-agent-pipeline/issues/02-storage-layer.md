Status: needs-triage

# Storage layer: JSON read/write + schema validation

## What to build

Implement the storage abstraction that all three agents use to read and write data. The storage layer enforces the JSON schemas defined in AGENTS.md, handles file naming conventions, and manages the `knowledge/` directory structure.

End-to-end behavior: an agent calls `storage.write_raw(source, items)` and a valid `knowledge/raw/{source}_{timestamp}.json` appears; another agent calls `storage.read_raw_latest()` and gets the most recent raw data.

## Acceptance criteria

- [ ] `src/storage/raw.py` — `write_raw(source, items) -> Path`, `read_raw_latest() -> dict`, `read_raw(path) -> dict`
- [ ] `src/storage/articles.py` — `write_analysis(articles) -> Path`, `read_latest_analysis() -> list[dict]`, `write_article(article) -> Path`, `read_draft_articles() -> list[dict]`, `archive_analysis(path)` (move to `.processed/`)
- [ ] File naming follows AGENTS.md: `{source}_{YYYYMMDD_HHMMSS}.json` for raw, `{YYYYMMDD}-{source}-analysis.json` for analysis, `{date}-{source}-{slug}.json` for articles
- [ ] JSON schema validation on write — rejects malformed items with clear error messages
- [ ] `knowledge/raw/`, `knowledge/articles/`, `knowledge/articles/.processed/` directories auto-created on first write
- [ ] All functions have type annotations and docstrings
- [ ] Unit tests with >80% coverage

## Blocked by

- `.scratch/three-agent-pipeline/issues/01-project-scaffold.md`
