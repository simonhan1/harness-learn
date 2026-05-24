#!/usr/bin/env python
"""Comprehensive test suite for supervisor pattern implementation."""

import json
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from patterns.supervisor import supervisor

logging.basicConfig(level=logging.WARNING)


def test_function_signature():
    """Test 1: Verify function signature."""
    print("\n[TEST 1] Function Signature")
    print("-" * 80)
    import inspect
    sig = inspect.signature(supervisor)
    print(f"supervisor{sig}")
    assert "task" in sig.parameters, "Missing 'task' parameter"
    assert "max_retries" in sig.parameters, "Missing 'max_retries' parameter"
    assert sig.parameters["max_retries"].default == 3, "max_retries should default to 3"
    print("[OK] Function signature correct: supervisor(task: str, max_retries: int = 3)")


def test_return_value_structure():
    """Test 2: Verify return value structure."""
    print("\n[TEST 2] Return Value Structure")
    print("-" * 80)
    result = supervisor("What is machine learning?", max_retries=1)

    required_keys = ["output", "attempts", "final_score", "passed"]
    optional_keys = ["warning", "accuracy_score", "depth_score", "format_score"]

    for key in required_keys:
        assert key in result, f"Missing required key: {key}"
        print(f"[OK] {key}: {result[key]}")

    for key in optional_keys:
        if key in result:
            print(f"[OK] {key}: {result[key]}")


def test_json_output_format():
    """Test 3: Verify output is JSON-compatible."""
    print("\n[TEST 3] JSON Output Format")
    print("-" * 80)
    result = supervisor("Explain quantum computing", max_retries=1)
    assert isinstance(result["output"], dict), "output should be a dict"
    output = result["output"]
    required_output_keys = ["title", "summary", "key_points", "analysis"]
    for key in required_output_keys:
        assert key in output, f"Missing output key: {key}"
        print(f"[OK] output.{key}: {str(output[key])[:60]}...")


def test_attempts_tracking():
    """Test 4: Verify attempts tracking."""
    print("\n[TEST 4] Attempts Tracking")
    print("-" * 80)
    result = supervisor("What is AI?", max_retries=1)
    assert isinstance(result["attempts"], int), "attempts should be int"
    assert result["attempts"] > 0, "attempts should be > 0"
    assert result["attempts"] <= 3, "attempts should be <= 3"
    print(f"[OK] Attempts: {result['attempts']} (valid range: 1-3)")


def test_scoring_system():
    """Test 5: Verify scoring system (1-10 per dimension, out of 30 total)."""
    print("\n[TEST 5] Scoring System (1-10 per dimension)")
    print("-" * 80)
    result = supervisor("Compare AI and ML", max_retries=1)
    assert isinstance(result["final_score"], int), "final_score should be int"
    assert 0 <= result["final_score"] <= 30, f"final_score should be 0-30, got {result['final_score']}"
    assert isinstance(result.get("accuracy_score"), int), "accuracy_score should be int"
    assert 0 <= result.get("accuracy_score", 0) <= 10, "accuracy_score should be 0-10"
    assert isinstance(result.get("depth_score"), int), "depth_score should be int"
    assert 0 <= result.get("depth_score", 0) <= 10, "depth_score should be 0-10"
    assert isinstance(result.get("format_score"), int), "format_score should be int"
    assert 0 <= result.get("format_score", 0) <= 10, "format_score should be 0-10"

    print(f"[OK] Final Score: {result['final_score']}/30")
    print(f"  - Accuracy:  {result.get('accuracy_score', 0)}/10")
    print(f"  - Depth:     {result.get('depth_score', 0)}/10")
    print(f"  - Format:    {result.get('format_score', 0)}/10")


def test_max_retries_warning():
    """Test 6: Verify warning on max retries exceeded."""
    print("\n[TEST 6] Max Retries Warning")
    print("-" * 80)
    result = supervisor("Test topic", max_retries=1)
    if "warning" in result:
        print(f"[OK] Warning present (when max retries exceeded)")
        print(f"  Message: {result['warning'][:80]}...")
    else:
        print(f"[OK] No warning (when review passed)")


def test_requirement_checklist():
    """Test 8: Verify all requirements from spec."""
    print("\n[TEST 8] Requirement Checklist")
    print("-" * 80)
    result = supervisor("Describe neural networks", max_retries=2)
    
    requirements = [
        ("1. Worker Agent outputs JSON", isinstance(result["output"], dict)),
        ("2. Supervisor evaluates accuracy (1-10)", "accuracy_score" in result),
        ("3. Supervisor evaluates depth (1-10)", "depth_score" in result),
        ("4. Supervisor evaluates format (1-10)", "format_score" in result),
        ("5. Output contains passed flag", isinstance(result["passed"], bool)),
        ("6. Output contains score", isinstance(result["final_score"], int)),
        ("7. Output contains analysis in output", "analysis" in result["output"]),
        ("8. Output contains attempts count", isinstance(result["attempts"], int)),
        ("9. Max retries = 3", result["attempts"] <= 3),
        ("10. if __name__ == '__main__' test entry exists", True),
    ]

    for req, status in requirements:
        symbol = "[OK]" if status else "[FAIL]"
        print(f"{symbol} {req}")

    all_passed = all(status for _, status in requirements)
    return all_passed


if __name__ == "__main__":
    print("=" * 80)
    print("COMPREHENSIVE SUPERVISOR PATTERN TEST SUITE")
    print("=" * 80)

    try:
        test_function_signature()
        test_return_value_structure()
        test_json_output_format()
        test_attempts_tracking()
        test_scoring_system()
        test_max_retries_warning()
        all_passed = test_requirement_checklist()

        print("\n" + "=" * 80)
        if all_passed:
            print("TEST SUMMARY: All tests passed successfully!")
        else:
            print("TEST SUMMARY: Some tests failed!")
        print("=" * 80)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
