## ADDED Requirements

### Requirement: Classify HTTP errors as retryable or not

The system SHALL distinguish between retryable HTTP errors (5xx, timeouts, connection failures) and non-retryable errors (4xx client errors, authentication failures) to avoid wasting retry attempts on unrecoverable errors.

#### Scenario: Server error (5xx) is retryable
- **WHEN** LLM API returns 500, 502, 503, or 504
- **THEN** system SHALL retry the request with exponential backoff (1s, 2s, 4s)

#### Scenario: Client error (4xx) is not retryable
- **WHEN** LLM API returns 400, 401, 403, 404
- **THEN** system SHALL NOT retry and SHALL raise the error immediately

#### Scenario: Request timeout is retryable
- **WHEN** HTTP request times out (exceeds 60 seconds)
- **THEN** system SHALL retry the request with exponential backoff (1s, 2s, 4s)

#### Scenario: Network connection error is retryable
- **WHEN** httpx.RequestError occurs (DNS failure, connection refused, etc.)
- **THEN** system SHALL retry the request with exponential backoff (1s, 2s, 4s)

### Requirement: Retry configuration is consistent

The system SHALL use a uniform retry strategy across all retry-enabled operations: maximum 3 attempts with exponential backoff (base delay 1.0 second).

#### Scenario: Retry attempts follow exponential backoff
- **WHEN** LLM call fails on attempt 1
- **THEN** system waits 1.0 second before attempt 2
- **WHEN** attempt 2 fails
- **THEN** system waits 2.0 seconds before attempt 3

#### Scenario: Retry stops after 3 attempts
- **WHEN** all 3 retry attempts fail
- **THEN** system SHALL raise RuntimeError without further retries
