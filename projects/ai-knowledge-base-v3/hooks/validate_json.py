#!/usr/bin/env python3
"""Validate knowledge base JSON files against schema rules.

Usage:
    python hooks/validate_json.py <json_file> [json_file2 ...]

Supports single files, multiple files, and wildcard patterns (e.g. *.json).
Exit 0 on success, exit 1 with error list and summary on failure.
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES: set[str] = {"draft", "review", "published", "archived"}
VALID_AUDIENCES: set[str] = {"beginner", "intermediate", "advanced"}

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://\S+")
SUMMARY_MIN_CHARS: int = 20
TAGS_MIN_COUNT: int = 1
SCORE_MIN: int = 1
SCORE_MAX: int = 10


def resolve_files(args: list[str]) -> list[Path]:
    """Resolve CLI arguments to a list of existing JSON file paths.

    Supports explicit file paths and glob wildcards (*.json).

    Args:
        args: Command-line arguments (file paths or glob patterns).

    Returns:
        Sorted list of unique Path objects for existing .json files.
    """
    filepaths: list[Path] = []
    seen: set[Path] = set()

    for arg in args:
        if "*" in arg or "?" in arg or "[" in arg:
            base = Path(arg)
            parent = base.parent
            pattern = base.name
            matches = sorted(parent.glob(pattern))
            if not matches:
                logger.warning("No files matched pattern: %s", arg)
            for m in matches:
                if m.is_file() and m not in seen:
                    filepaths.append(m)
                    seen.add(m)
        else:
            p = Path(arg)
            if p.is_file():
                if p not in seen:
                    filepaths.append(p)
                    seen.add(p)
            else:
                logger.warning("File not found: %s", p)

    return filepaths


def _field_error(prefix: str, field: str, expected: type, actual: Any) -> str:
    """Format a type-mismatch error message."""
    return (
        f"{prefix}: field '{field}' type mismatch, "
        f"expected {expected.__name__}, got {type(actual).__name__}"
    )


def validate_entry(data: dict[str, Any], filepath: Path) -> list[str]:
    """Validate a single JSON object against knowledge base schema.

    Args:
        data: Parsed JSON object (dict).
        filepath: Source file path (for error messages).

    Returns:
        List of error strings. Empty list means valid.
    """
    errors: list[str] = []
    prefix = filepath.name

    _id = data.get("id")
    _title = data.get("title")
    _source_url = data.get("source_url")
    _summary = data.get("summary")
    _tags = data.get("tags")
    _status = data.get("status")

    # Required fields presence + type check
    for field, expected_type in REQUIRED_FIELDS.items():
        value = data.get(field)
        if field not in data or value is None:
            errors.append(f"{prefix}: missing required field '{field}'")
        elif not isinstance(value, expected_type):
            errors.append(_field_error(prefix, field, expected_type, value))

    # ID format: {source}-{YYYYMMDD}-{NNN}
    if isinstance(_id, str) and not ID_PATTERN.match(_id):
        errors.append(
            f"{prefix}: invalid ID format '{_id}', "
            f"expected {{source}}-{{YYYYMMDD}}-{{NNN}} (e.g. github-20260317-001)"
        )

    # Status enum
    if isinstance(_status, str) and _status not in VALID_STATUSES:
        errors.append(
            f"{prefix}: invalid status '{_status}', "
            f"allowed: {', '.join(sorted(VALID_STATUSES))}"
        )

    # URL format
    if isinstance(_source_url, str) and not URL_PATTERN.match(_source_url):
        errors.append(
            f"{prefix}: invalid source_url format '{_source_url}'"
        )

    # Summary length
    if isinstance(_summary, str) and len(_summary) < SUMMARY_MIN_CHARS:
        errors.append(
            f"{prefix}: summary too short ({len(_summary)} chars), "
            f"minimum {SUMMARY_MIN_CHARS}"
        )

    # Tags count
    if isinstance(_tags, list) and len(_tags) < TAGS_MIN_COUNT:
        errors.append(
            f"{prefix}: need at least {TAGS_MIN_COUNT} tag(s), got {len(_tags)}"
        )

    # Score (optional)
    if "score" in data:
        score = data["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            errors.append(f"{prefix}: 'score' must be numeric")
        elif not (SCORE_MIN <= score <= SCORE_MAX):
            errors.append(
                f"{prefix}: score {score} out of range [{SCORE_MIN}, {SCORE_MAX}]"
            )

    # Audience (optional)
    if "audience" in data:
        audience = data["audience"]
        if not isinstance(audience, str):
            errors.append(f"{prefix}: 'audience' must be a string")
        elif audience not in VALID_AUDIENCES:
            errors.append(
                f"{prefix}: invalid audience '{audience}', "
                f"allowed: {', '.join(sorted(VALID_AUDIENCES))}"
            )

    return errors


def validate_file(filepath: Path) -> list[str]:
    """Read and validate a JSON file.

    Args:
        filepath: Path to the JSON file.

    Returns:
        List of error strings. Empty list means valid.
    """
    try:
        raw = filepath.read_text(encoding="utf-8")
    except OSError as e:
        return [f"{filepath.name}: read error: {e}"]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return [f"{filepath.name}: JSON parse error: {e}"]

    if not isinstance(data, dict):
        return [f"{filepath.name}: root must be a JSON object, got {type(data).__name__}"]

    return validate_entry(data, filepath)


def main() -> None:
    """Entry point: parse args, validate files, report summary, set exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if len(sys.argv) < 2:
        logger.error(
            "Usage: python hooks/validate_json.py <json_file> [json_file2 ...]"
        )
        sys.exit(2)

    filepaths = resolve_files(sys.argv[1:])

    if not filepaths:
        logger.error("No files to validate")
        sys.exit(2)

    total_errors = 0
    passed = 0
    failed = 0

    for fp in filepaths:
        errors = validate_file(fp)
        if errors:
            failed += 1
            for err in errors:
                total_errors += 1
                logger.error(err)
        else:
            passed += 1
            logger.info("PASS: %s", fp.name)

    total = passed + failed
    logger.info("=" * 50)
    logger.info("Validation complete")
    logger.info("  Files checked: %d", total)
    logger.info("  Passed:        %d", passed)
    logger.info("  Failed:        %d", failed)
    logger.info("  Total errors:  %d", total_errors)

    sys.exit(1 if total_errors > 0 else 0)


if __name__ == "__main__":
    main()
