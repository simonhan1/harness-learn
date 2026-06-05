#!/usr/bin/env python3
"""Workflow integration test using compiled LangGraph app.

Demonstrates the full pipeline:
    planner → collector → analyzer → reviewer → [organize | revise → reviewer] | human_flag

Usage:
    python workflows/test_nodes.py
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

from state import KBState
from graph import build_graph


def run_workflow():
    """Run the complete workflow via compiled graph."""
    print("=" * 80)
    print("LangGraph Workflow Demo (new topology)")
    print("=" * 80)

    initial_state: KBState = {
        "plan": {},
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
        "needs_human_review": False,
    }

    app = build_graph()

    # Collect final state from stream
    final_state = {}
    for step in app.stream(initial_state):
        for node_name, output in step.items():
            final_state.update(output)
            print(f"\n─── {node_name} ───")
            if node_name == "planner":
                plan = output.get("plan", {})
                print(f"  tier={plan.get('tier')}, target={plan.get('target_count')}")
            elif node_name == "collect":
                sources = output.get("sources", [])
                print(f"  sources={len(sources)}")
            elif node_name == "analyze":
                articles = output.get("articles", [])
                print(f"  articles={len(articles)}")
            elif node_name == "review":
                print(f"  passed={output.get('review_passed')}, iteration={output.get('iteration')}")
            elif node_name == "revise":
                print(f"  analyses updated={len(output.get('analyses', []))}")
            elif node_name == "organize":
                print("  done (saved + index updated)")
            elif node_name == "human_flag":
                print(f"  needs_human_review={output.get('needs_human_review')}")

    # Summary
    print("\n" + "=" * 80)
    print("Workflow Summary")
    print("=" * 80)
    print(f"Sites: {len(final_state.get('sources', []))}")
    print(f"Articles: {len(final_state.get('articles', []))}")
    print(f"Iteration: {final_state.get('iteration', 0)}")
    print(f"Review passed: {final_state.get('review_passed', False)}")
    print(f"Needs human review: {final_state.get('needs_human_review', False)}")
    ct = final_state.get("cost_tracker", {})
    print(f"API calls: {ct.get('total_api_calls', 0)}")
    print(f"Est. cost: ${ct.get('estimated_cost_usd', 0):.6f}")
    print("=" * 80)


if __name__ == "__main__":
    try:
        run_workflow()
    except Exception as e:
        logging.error("Workflow error: %s", e, exc_info=True)
        sys.exit(1)
