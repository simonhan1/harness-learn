#!/usr/bin/env python3
"""Simple test script for LangGraph workflow nodes.

This demonstrates how to use the 5 nodes in sequence:
1. collect_node — Fetch GitHub trending data
2. analyze_node — LLM analysis of each item
3. organize_node — Dedup, filter, and correct
4. review_node — 4D review and scoring
5. save_node — Save to knowledge base

Usage:
    python workflows/test_nodes.py
"""

import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# Initialize state
from state import KBState
from nodes import (
    collect_node,
    analyze_node,
    organize_node,
    review_node,
    save_node,
)

# Create initial state
initial_state: KBState = {
    "sources": [],
    "analyses": [],
    "articles": [],
    "review_feedback": "",
    "review_passed": False,
    "iteration": 0,
    "cost_tracker": {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_api_calls": 0,
        "model_used": "deepseek-chat",
        "estimated_cost_usd": 0.0,
        "calls_by_node": {},
    },
}


def run_workflow():
    """Run the complete workflow with demo state updates."""
    
    print("=" * 80)
    print("LangGraph Workflow Demo")
    print("=" * 80)
    
    state = initial_state.copy()
    
    # Step 1: Collect
    print("\n[Step 1] Running collect_node...")
    print("-" * 80)
    try:
        state.update(collect_node(state))
        print(f"✓ Collect complete. Sources: {len(state['sources'])}")
        if state['sources']:
            for src in state['sources']:
                print(f"  - {src['source']}: {src['count']} items")
    except Exception as e:
        print(f"✗ Collect failed: {e}")
        return
    
    if not state['sources']:
        print("⚠ No sources collected, stopping workflow")
        return
    
    # Step 2: Analyze
    print("\n[Step 2] Running analyze_node...")
    print("-" * 80)
    try:
        state.update(analyze_node(state))
        print(f"✓ Analysis complete. Articles: {len(state['articles'])}")
        if state['articles']:
            for article in state['articles'][:3]:  # Show first 3
                print(f"  - {article.get('id')}: {article.get('title')[:50]}")
                print(f"    Score: {article.get('relevance_score')}, Tags: {article.get('tags')[:2]}")
            if len(state['articles']) > 3:
                print(f"  ... and {len(state['articles']) - 3} more")
        print(f"  Cost tracker: {state['cost_tracker']['total_api_calls']} API calls")
    except Exception as e:
        print(f"✗ Analysis failed: {e}")
        return
    
    if not state['articles']:
        print("⚠ No articles analyzed, stopping workflow")
        return
    
    # Step 3: Organize
    print("\n[Step 3] Running organize_node (iteration 0)...")
    print("-" * 80)
    try:
        state.update(organize_node(state))
        print(f"✓ Organization complete. Articles after dedup/filter: {len(state['articles'])}")
    except Exception as e:
        print(f"✗ Organization failed: {e}")
        return
    
    if not state['articles']:
        print("⚠ No articles after organization, stopping workflow")
        return
    
    # Step 4: Review (iteration 0)
    print("\n[Step 4] Running review_node (iteration 0)...")
    print("-" * 80)
    try:
        state.update(review_node(state))
        print(f"✓ Review complete.")
        print(f"  - Passed: {state['review_passed']}")
        print(f"  - Iteration: {state['iteration']}")
        print(f"  - Feedback: {state['review_feedback'][:100]}...")
    except Exception as e:
        print(f"✗ Review failed: {e}")
        return
    
    # If review didn't pass, optionally do organize + review again
    if not state['review_passed'] and state['iteration'] < 2:
        print("\n[Step 3b] Running organize_node (iteration 1 with feedback)...")
        print("-" * 80)
        try:
            state.update(organize_node(state))
            print(f"✓ Reorganization with feedback complete. Articles: {len(state['articles'])}")
        except Exception as e:
            print(f"✗ Reorganization failed: {e}")
        
        print("\n[Step 4b] Running review_node (iteration 1)...")
        print("-" * 80)
        try:
            state.update(review_node(state))
            print(f"✓ Review complete.")
            print(f"  - Passed: {state['review_passed']}")
            print(f"  - Iteration: {state['iteration']}")
        except Exception as e:
            print(f"✗ Review failed: {e}")
    
    # Step 5: Save
    print("\n[Step 5] Running save_node...")
    print("-" * 80)
    try:
        state.update(save_node(state))
        print(f"✓ Save complete.")
    except Exception as e:
        print(f"✗ Save failed: {e}")
        return
    
    # Summary
    print("\n" + "=" * 80)
    print("Workflow Summary")
    print("=" * 80)
    print(f"Total sources processed: {len(state['sources'])}")
    print(f"Total articles created: {len(state['articles'])}")
    print(f"Final iteration count: {state['iteration']}")
    print(f"Review passed: {state['review_passed']}")
    cost_tracker = state.get('cost_tracker', {})
    print(f"\nCost Summary:")
    print(f"  - Total API calls: {cost_tracker.get('total_api_calls', 0)}")
    print(f"  - Input tokens: {cost_tracker.get('total_input_tokens', 0)}")
    print(f"  - Output tokens: {cost_tracker.get('total_output_tokens', 0)}")
    print(f"  - Estimated cost: ${cost_tracker.get('estimated_cost_usd', 0):.6f}")
    print("=" * 80)


if __name__ == "__main__":
    try:
        run_workflow()
    except Exception as e:
        logging.error("Workflow error: %s", e, exc_info=True)
        sys.exit(1)
