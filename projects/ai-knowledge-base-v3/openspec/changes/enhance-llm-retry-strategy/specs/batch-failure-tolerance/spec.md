## ADDED Requirements

### Requirement: Single item failure does not interrupt batch analysis

When analyzing multiple items in a batch, if one item's LLM call fails after all retries, the system SHALL mark that item as `analysis_failed` and continue analyzing remaining items without interruption.

#### Scenario: Batch continues after one failure
- **WHEN** analyzing 10 items and item #5 exhausts all retry attempts
- **THEN** item #5 is marked with `status: "analysis_failed"` and items #6-10 continue processing

#### Scenario: All items are processed regardless of individual failures
- **WHEN** batch contains 10 items with 3 failures
- **THEN** analyze() returns all 10 items with status set to either "draft" (success) or "analysis_failed" (failure)

### Requirement: JSON parsing errors are not retried

When the LLM API returns HTTP 200 but the response body cannot be parsed as valid JSON, the system SHALL treat this as an unrecoverable error (not retry) and mark the item as `analysis_failed`.

#### Scenario: Malformed JSON response fails without retry
- **WHEN** LLM API returns 200 with content `{"title": "foo"` (truncated/malformed)
- **THEN** _parse_json_response() raises JSONDecodeError, item is marked `analysis_failed`, and batch processing continues

#### Scenario: Analysis failure does not propagate to downstream
- **WHEN** item has `status: "analysis_failed"`
- **THEN** organize() and save() steps still process it (may archive it based on relevance_score if available)

### Requirement: Batch analysis returns detailed failure information

The system SHALL provide visibility into which items succeeded and which failed, including failure reasons in logs.

#### Scenario: Analysis logs show success and failure counts
- **WHEN** analyze() completes a batch
- **THEN** logger outputs: "Analysis complete: X success, Y failed, Z total"

#### Scenario: Failed items include error context
- **WHEN** item analysis fails
- **THEN** item dict includes failure details in `ai_analysis` field (or is None) for later investigation
