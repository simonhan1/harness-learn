#!/usr/bin/env python
"""Usage examples for the Supervisor pattern implementation."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from patterns.supervisor import supervisor


if __name__ == "__main__":
    print("=" * 80)
    print("SUPERVISOR PATTERN - USAGE EXAMPLE")
    print("=" * 80)

    # Example 1: Basic usage
    print("\n[Example 1] Basic Supervisor Usage")
    print("-" * 80)
    print("Task: Explain the difference between AI and Machine Learning\n")

    result = supervisor(
        "Explain the difference between AI and Machine Learning",
        max_retries=2
    )

    print(f"Result Status: {'PASSED' if result['passed'] else 'FAILED'}")
    print(f"Attempts: {result['attempts']}")
    print(f"Scores: Accuracy={result['accuracy_score']}, Depth={result['depth_score']}, Format={result['format_score']}")
    print(f"Total Score: {result['final_score']}/30")

    output = result["output"]
    print(f"\nGenerated Analysis:")
    print(f"  Title: {output['title']}")
    print(f"  Summary: {output['summary'][:150]}...")
    print(f"  Key Points: {len(output['key_points'])} points generated")

    if "warning" in result:
        print(f"\nWarning: {result['warning']}")

    # Example 2: Return value structure
    print("\n[Example 2] Return Value Structure")
    print("-" * 80)
    print("The supervisor function returns a dict with the following keys:\n")
    for key in result.keys():
        value = result[key]
        if isinstance(value, dict) and len(str(value)) > 100:
            print(f"  - {key}: <dict with {len(value)} keys>")
        elif isinstance(value, list) and len(value) > 3:
            print(f"  - {key}: <list with {len(value)} items>")
        else:
            print(f"  - {key}: {value}")

    print("\n" + "=" * 80)
    print("Implementation Complete!")
    print("=" * 80)
    print("\nKey Features Implemented:")
    print("  1. Worker Agent: Generates JSON-formatted analysis reports")
    print("  2. Supervisor Agent: Evaluates on accuracy (1-10), depth (1-10), format (1-10)")
    print("  3. Iterative Refinement: Retries up to 3 times with feedback")
    print("  4. Quality Threshold: Pass if total score >= 21/30")
    print("  5. Max Retries Handling: Returns with warning after 3 attempts")
    print("=" * 80)
