Status: needs-triage

# Scheduler + progress tracking

## What to build

Add a daily scheduling mechanism that triggers the pipeline at UTC 0:00, and implement progress tracking so each run's status is recorded and re-runs don't process the same raw data twice. Addresses the PRD open questions "retry strategy?" and "progress tracking?"

End-to-end behavior: at UTC 0:00 daily, the pipeline runs automatically. A progress log records each run's start/end, agent statuses, and item counts. If a run is re-triggered before the previous one finishes, it waits.

## Acceptance criteria

- [ ] `src/scheduler.py` — uses `schedule` or `APScheduler` to trigger `run_pipeline()` daily at UTC 0:00
- [ ] Progress tracking: each run writes a run log to `knowledge/.runs/{timestamp}.json` with per-agent status, item counts, and errors
- [ ] Run log schema: `{run_id, started_at, completed_at, agents: [{name, status, items_processed, error}]}`
- [ ] Re-run safety: before each agent runs, check if raw/analysis files already processed for today's batch (compare timestamps against run log)
- [ ] Signal handling: SIGTERM/SIGINT gracefully stops the pipeline, logs partial run
- [ ] Manual run support: `python -m src.scheduler --now` triggers immediate run for debugging
- [ ] Integration test: scheduler triggers pipeline, run log written correctly

## Blocked by

- `.scratch/three-agent-pipeline/issues/06-pipeline-orchestration.md`
