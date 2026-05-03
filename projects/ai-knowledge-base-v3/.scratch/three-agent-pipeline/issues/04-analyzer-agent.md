Status: needs-triage

# Analyzer Agent: raw data → AI analysis

## What to build

Implement the analyzer agent that reads the latest raw data, calls the AI model to deduplicate/classify/summarize/score each item, and outputs a batch analysis JSON. Follows AGENTS.md section 2.2 rules: all items default to `status: "draft"`.

End-to-end behavior: run analyzer after collector → produces `knowledge/articles/{date}-{source}-analysis.json` containing every raw item with added `summary`, `tags`, `category`, `status: "draft"`, and `ai_analysis` block.

## Acceptance criteria

- [ ] `src/analyzer/agent.py` — reads latest raw file via storage, calls AI model for analysis, writes analysis JSON via storage
- [ ] Dedup: URL exact match + title similarity ≥0.85 marks duplicate (skip, log as duplicate)
- [ ] AI call per item: generate Chinese summary (1-3 sentences), tags (list of strings), category (`model_release`/`agent_framework`/`tool`/`paper`/`opinion`), relevance score (1-10)
- [ ] AI call retry: 2 attempts per item, mark `status: "analysis_failed"` if both fail, do not block other items
- [ ] All items default to `status: "draft"` — never set to `"published"`
- [ ] AI model/URL from config (not hardcoded)
- [ ] `id` field generated as `kb-YYYYMMDD-NNN`
- [ ] Unit tests with >80% coverage (mock AI, verify dedup, verify schema, verify retry/failure)

## Blocked by

- `.scratch/three-agent-pipeline/issues/02-storage-layer.md`
- `.scratch/three-agent-pipeline/issues/03-collector-agent.md`
