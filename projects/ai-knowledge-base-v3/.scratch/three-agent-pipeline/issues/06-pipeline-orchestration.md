Status: needs-triage

# Pipeline orchestration: LangGraph state graph

## What to build

Wire the three agents into a LangGraph state graph that runs collector → analyzer → organizer as a serial DAG. Implement error propagation: if an upstream agent produces no output, downstream agents skip gracefully. This slice handles the PRD open question "What happens when upstream fails?"

End-to-end behavior: invoke the pipeline → collector runs, analyzer runs on collector output, organizer runs on analyzer output. If collector fails entirely, the pipeline stops with a clear error; if analyzer fails on some items, organizer still processes the successful ones.

## Acceptance criteria

- [ ] `src/pipeline.py` or `src/workflow.py` — LangGraph StateGraph with three nodes (collect, analyze, organize) and linear edges
- [ ] State object carries: `raw_files: list[Path]`, `analysis_files: list[Path]`, `errors: list[str]`, `status: str`
- [ ] Collector node writes raw files, updates state with file paths
- [ ] Analyzer node reads raw files from state, writes analysis, updates state — if no raw files exist, skips with INFO log
- [ ] Organizer node reads analysis from state, writes articles, updates state — if no analysis exists, skips with INFO log
- [ ] Pipeline entry point: `run_pipeline()` that returns final state (success/partial/failed)
- [ ] Each agent runs in a try/except; failures logged at ERROR level with traceback, pipeline continues or stops based on severity
- [ ] Integration test: end-to-end run with mock collector → mock analyzer → mock organizer

## Blocked by

- `.scratch/three-agent-pipeline/issues/03-collector-agent.md`
- `.scratch/three-agent-pipeline/issues/04-analyzer-agent.md`
- `.scratch/three-agent-pipeline/issues/05-organizer-agent.md`
