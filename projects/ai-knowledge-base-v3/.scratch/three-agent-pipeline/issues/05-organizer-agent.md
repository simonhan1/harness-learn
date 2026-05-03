Status: needs-triage

# Organizer Agent: analysis → individual articles + archive

## What to build

Implement the organizer agent that reads the batch analysis output, filters low-quality items, generates individual per-article JSON files, and archives the intermediate analysis file. Follows AGENTS.md section 2.3.

End-to-end behavior: run organizer after analyzer → produces one `knowledge/articles/{date}-{source}-{slug}.json` per qualifying article, moves `*-analysis.json` to `.processed/`.

## Acceptance criteria

- [ ] `src/organizer/agent.py` — reads latest analysis file, filters + validates, writes individual article files, archives intermediate
- [ ] Filter: `relevance_score < 5` items excluded (log at INFO level)
- [ ] Sort: remaining items by `relevance_score` descending
- [ ] Validate each article against the full knowledge entry schema before writing
- [ ] File naming: `{date}-{source}-{slug}.json` where `slug` is URL-safe title slug
- [ ] After successful write, move intermediate `*-analysis.json` to `knowledge/articles/.processed/`
- [ ] Unit tests with >80% coverage (verify filtering, verify ordering, verify archive, verify validation)

## Blocked by

- `.scratch/three-agent-pipeline/issues/02-storage-layer.md`
- `.scratch/three-agent-pipeline/issues/04-analyzer-agent.md`
