Status: needs-triage

# Collector Agent: GitHub Trending + Hacker News → raw JSON

## What to build

Implement the collector agent that fetches AI-related content from GitHub Trending Top 50 and Hacker News, filters non-AI content, and writes structured raw JSON to `knowledge/raw/`. Follows the retry and rate-limiting rules from AGENTS.md section 2.1.

End-to-end behavior: running the collector produces `knowledge/raw/github_trending_{timestamp}.json` and `knowledge/raw/hacker_news_{timestamp}.json` with at least 15 AI-filtered items total.

## Acceptance criteria

- [ ] `src/collector/github.py` — fetch GitHub Trending Top 50 (via requests or OpenClaw), filter AI-related repos by keyword matching (AI, LLM, agent, ML, etc.)
- [ ] `src/collector/hackernews.py` — fetch Hacker News front page (via HN API or scraping), filter AI-related posts
- [ ] Rate limiting: ≥30s between requests to the same source
- [ ] Retry: 3 attempts per source with exponential backoff (1s → 4s → 16s)
- [ ] All sources fail → log ERROR and exit gracefully (no uncaught exceptions)
- [ ] Output matches `knowledge/raw/` schema: `{source, collected_at, items[{name, url, description, stars/language}]}`
- [ ] Uses `src/storage/raw.py` for file I/O
- [ ] Unit tests with >80% coverage (mock HTTP, verify retry, verify AI filter, verify format)

## Blocked by

- `.scratch/three-agent-pipeline/issues/02-storage-layer.md`
