"""Patterns module - reusable design patterns for AI knowledge base.

This module provides common design patterns used throughout the project:
- router: Two-layer intent classification for query routing
"""

from patterns.router import (
    classify_intent_with_llm,
    detect_intent_by_keywords,
    handle_general_chat,
    handle_github_search,
    handle_knowledge_query,
    route,
)

__all__ = [
    "route",
    "detect_intent_by_keywords",
    "classify_intent_with_llm",
    "handle_github_search",
    "handle_knowledge_query",
    "handle_general_chat",
]
