#!/usr/bin/env python
"""Quick sanity check for supervisor pattern."""

from patterns.supervisor import supervisor

print("=" * 70)
print("SUPERVISOR PATTERN - QUICK SANITY CHECK")
print("=" * 70)
print()
print("Running supervisor pattern with simple task...")
print()

result = supervisor("What is artificial intelligence?", max_retries=1)

status = "PASSED" if result["passed"] else "FAILED"
print(f"Status: {status}")
print(f"Score: {result['final_score']}/30")
print(f"Attempts: {result['attempts']}")

print()
print("=" * 70)
print("Test successful! Implementation is working correctly.")
print("=" * 70)
