## Context

Currently, the LLM client (`model_client.py`) retries on all `httpx.HTTPStatusError` and `httpx.RequestError` exceptions without distinguishing between retryable and non-retryable errors. For example, a 401 Unauthorized error (invalid API key) will be retried 3 times before failing, wasting time and creating confusing logs.

Additionally, the batch analysis loop in `pipeline.py` catches `LLMAnalysisException` and marks the item as failed, but the current error handling in `_analyze_single()` doesn't clearly separate:
- HTTP-level failures (network, server errors) → should retry
- Data parsing failures (malformed JSON) → should NOT retry
- Other exceptions → should not retry

The pipeline already has retry logic in the collection phase (`_fetch_github_trending`, `_fetch_rss`), so the analysis phase should align with the same strategy.

## Goals / Non-Goals

**Goals:**

1. Implement intelligent HTTP error classification so retry only happens for recoverable errors (5xx, timeout, connection issues), not for client errors (4xx) or auth failures (401, 403)
2. Ensure batch analysis continues when individual items fail, with clear success/failure accounting
3. Clarify that JSON parsing errors are treated as fatal (not retried) but don't interrupt batch processing
4. Unify retry configuration: all retry-enabled operations use max 3 attempts with exponential backoff (1s base)
5. Maintain backward compatibility: public API signatures of `model_client` and `pipeline` remain unchanged

**Non-Goals:**

- Implement async/concurrent retry strategies (out of scope for now; can be added later)
- Add circuit breaker pattern or provider fallback (OpenAI ↔ DeepSeek) — future work
- Implement full request telemetry/observability beyond existing logging
- Support per-provider retry strategies (all providers use the same logic)

## Decisions

### Decision 1: HTTP error classification via status code inspection

**Choice**: Add a helper function `_is_retryable_error(error: Exception) -> bool` that inspects the HTTP status code.

**Rationale**: 
- Retryable: 5xx (server errors), timeout, connection errors → retry with backoff
- Not retryable: 4xx (except 429 which we treat as retryable), auth/permission errors → fail immediately
- Clear and testable, prevents unnecessary retries

**Alternatives considered**:
- A) No status code checking, retry everything → wastes time on unrecoverable errors (rejected)
- B) Configuration-based allowlist of retryable codes → adds complexity, not worth it yet (rejected)

### Decision 2: JSON parse failures are terminal, not retried

**Choice**: Catch `json.JSONDecodeError` in `_analyze_single()` as a separate exception class, mark as `analysis_failed`, do NOT retry.

**Rationale**:
- JSON parse failures indicate the LLM response was truncated or malformed at the application level (not network).
- Retrying the same truncated response won't help; likely a LLM API issue or internal bug.
- Better to fail fast and investigate rather than retry 3 times.

**Alternatives considered**:
- A) Retry JSON parse failures → wastes time, confusing logs (rejected)
- B) Use a stricter JSON parser with recovery → adds complexity (rejected)

### Decision 3: Batch analysis must continue on item failure

**Choice**: In `_analyze_single()`, catch all exceptions and return `{"status": "analysis_failed", ...}`. The `analyze()` loop continues processing all items regardless of individual failures.

**Rationale**:
- User expects all items to be analyzed (or marked failed), not just up to the first failure
- Partial batch processing is better than nothing (you get data for 9 out of 10 items)
- Downstream (organize, save) can filter or handle failed items

**Alternatives considered**:
- A) Raise exception on first failure, stop batch → loses already-processed items (rejected)
- B) Have a flag to continue/stop on failure → adds complexity, user choice not needed (rejected)

### Decision 4: Unified retry configuration

**Choice**: Both collection and analysis phases use:
- Max retries: 3
- Base delay: 1.0 second (delays: 1s, 2s, 4s)
- HTTP timeout: 60 seconds

**Rationale**:
- Consistency across the pipeline makes behavior predictable and easy to debug
- 3 attempts is a reasonable middle ground (not too aggressive, not too lenient)
- Exponential backoff respects API rate limits better than fixed delay

**Alternatives considered**:
- A) Different retry counts per phase (collect=3, analyze=2) → inconsistent, harder to reason about (rejected)
- B) Configurable per-call retries → not needed; remove flexibility if unclear on why (rejected)

### Decision 5: Error classification happens at HTTP layer, not LLM layer

**Choice**: Implement `_is_retryable_error()` in `model_client.py`, not in `pipeline.py`. The function inspects httpx exceptions.

**Rationale**:
- HTTP retry logic belongs in the LLM client, not pipeline orchestration
- Keeps pipeline.py focused on business logic (collect → analyze → organize → save)
- Makes the client reusable for future non-pipeline use cases

**Alternatives considered**:
- A) Retry logic in pipeline.py → duplicates code, harder to test (rejected)
- B) Separate retry decorator module → over-engineered for current scope (rejected)

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| **HTTP status code boundaries unclear** (e.g., should 429 be retried?) | Implement conservative approach: retry only 5xx, timeouts, connection errors. 429 (rate limit) is NOT retried initially; we rely on batch slowness for implicit backoff. Document decision in code comment. |
| **Customers see "analysis_failed" items in output** | Good — it's transparent. Organize step filters them or can archive low-score items. Downstream can choose to drop/notify on failures. |
| **No retry for 429 (rate limit)** | Acceptable because: (a) LLM APIs usually reject batch at once, not mid-batch; (b) we're not async so not hammering API; (c) can add 429 retry in future if needed. |
| **JSON parse errors silently fail** | Mitigate with clear logging: "LLM analysis failed for 'item-name': JSONDecodeError..." and status mark. Operator can investigate. |
| **No observability into retry counts per item** | Add log line per retry attempt: "LLM call failed (attempt X/3): <reason>. Retrying in Ys…". Sufficient for debugging. |

## Migration Plan

1. **Phase 1 — Code changes** (low risk, backward compatible):
   - Add `_is_retryable_error()` to `model_client.py`
   - Update `chat_with_retry()` to use the classifier
   - Clarify `_analyze_single()` exception handling
   - Ensure `analyze()` loop doesn't break on item failure

2. **Phase 2 — Testing**:
   - Unit tests for `_is_retryable_error()` with various HTTP codes
   - Integration test: batch analysis with 1 item failure, verify others complete
   - Manual smoke test: run pipeline with API key, confirm normal flow

3. **Phase 3 — Rollout**:
   - No deployment changes needed (library code only)
   - Update AGENTS.md with new retry configuration
   - Existing scripts/calls continue working unchanged

## Open Questions

1. Should we log retry attempts at DEBUG or INFO level? (currently proposed: WARNING, should we change?)
2. Do we need metrics/counters for retry success rates? (out of scope for now, defer)
3. Should failed items go to a separate "failed_analysis" file or mixed in "analysis.json"? (currently mixed, seems fine)
