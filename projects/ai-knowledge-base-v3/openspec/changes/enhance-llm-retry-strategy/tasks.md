## 1. model_client.py — HTTP Error Classification

- [ ] 1.1 Add `_is_retryable_error(error: Exception) -> bool` function to classify retryable vs non-retryable errors
- [ ] 1.2 Document in function docstring: retryable (5xx, timeouts, connection), not retryable (4xx except 429)
- [ ] 1.3 Update `chat_with_retry()` to call `_is_retryable_error()` before deciding to retry
- [ ] 1.4 Update log messages to indicate when error is not retryable ("Error is not retryable, raising immediately")
- [ ] 1.5 Write unit tests for `_is_retryable_error()` covering: 5xx codes, 4xx codes, timeout, connection errors

## 2. pipeline.py — Batch Failure Tolerance

- [ ] 2.1 Clarify `_analyze_single()` exception handling: catch `json.JSONDecodeError` separately, do NOT retry
- [ ] 2.2 Ensure `_analyze_single()` always returns a dict with `status` field set (either "draft" or "analysis_failed")
- [ ] 2.3 Update `analyze()` loop to count successes and failures, log final summary: "Analysis complete: X success, Y failed, Z total"
- [ ] 2.4 Verify `organize()` can handle items with `status: "analysis_failed"` without crashing
- [ ] 2.5 Write integration test: batch analyze 5 items where item #2 fails, verify items #1, 3-5 complete

## 3. Documentation Updates

- [ ] 3.1 Update AGENTS.md section 7 to add "7.1 Retry Configuration" with details: max 3 retries, 1s base delay, 60s timeout
- [ ] 3.2 Add comment in `model_client.py` explaining retry strategy and error classification
- [ ] 3.3 Add comment in `pipeline.py _analyze_single()` explaining that JSONDecodeError is not retried

## 4. Testing & Verification

- [ ] 4.1 Run existing tests to ensure backward compatibility
- [ ] 4.2 Test with mock: simulate 500 error on attempt 1, success on attempt 2 (verify retry happens)
- [ ] 4.3 Test with mock: simulate 401 error (verify no retry)
- [ ] 4.4 Test with mock: simulate JSONDecodeError (verify no retry, item marked failed)
- [ ] 4.5 Manual smoke test: run `python pipeline/pipeline.py --sources github --limit 5` and verify normal flow

## 5. Code Review & Cleanup

- [ ] 5.1 Review code for PEP 8 compliance and style consistency
- [ ] 5.2 Verify all error messages are clear and logged at appropriate levels
- [ ] 5.3 Check for any hardcoded values that should be constants (all should be at module top)
- [ ] 5.4 Final integration test: batch with mixed success/failure/timeout scenarios
