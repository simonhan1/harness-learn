"""Router pattern: Two-layer intent classification with keyword matching and LLM fallback.

This module implements a router that classifies user queries into three intent types:
- github_search: Search GitHub trending repositories
- knowledge_query: Query local knowledge base
- general_chat: General LLM-powered chat

The router uses a two-layer strategy:
1. First layer: Fast keyword matching (zero cost, no LLM call)
2. Second layer: LLM classification for ambiguous queries

Usage:
    from patterns.router import route
    
    response = route("How to use OpenAI API?")
    print(response)
"""

import json
import logging
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Add parent directory to path for relative imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.model_client import create_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Keywords for intent detection (first layer)
INTENT_KEYWORDS = {
    "github_search": [
        "github",
        "repo",
        "repository",
        "trending",
        "project",
        "open source",
        "source code",
        "开源",
        "仓库",
        "项目",
    ],
    "knowledge_query": [
        "knowledge base",
        "article",
        "summary",
        "knowledge",
        "learn",
        "find",
        "知识库",
        "文章",
        "查找",
        "学习",
    ],
}

# GitHub Search API configuration
GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
GITHUB_SEARCH_TIMEOUT = 30

# Knowledge base index path
KNOWLEDGE_BASE_PATH = Path(__file__).parent.parent / "knowledge" / "articles"


# ---------------------------------------------------------------------------
# Intent Classification (Layer 1: Keyword Matching)
# ---------------------------------------------------------------------------


def detect_intent_by_keywords(query: str) -> str | None:
    """Detect intent using keyword matching (layer 1, zero cost).

    Args:
        query: User query string.

    Returns:
        Intent type (github_search, knowledge_query) or None if no match.
    """
    query_lower = query.lower()

    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw.lower() in query_lower for kw in keywords):
            logger.debug("Intent detected by keyword: %s", intent)
            return intent

    return None


# ---------------------------------------------------------------------------
# Intent Classification (Layer 2: LLM Fallback)
# ---------------------------------------------------------------------------


def classify_intent_with_llm(query: str) -> str:
    """Classify intent using LLM when keyword matching fails (layer 2).

    Args:
        query: User query string.

    Returns:
        Intent type (github_search, knowledge_query, or general_chat).

    Raises:
        RuntimeError: If LLM call fails after retries.
    """
    client = create_client()

    system_prompt = """You are an intent classifier. Given a user query, classify it into one of three categories:
1. "github_search" - User wants to search for GitHub repositories or trending projects
2. "knowledge_query" - User wants to query the knowledge base or find articles
3. "general_chat" - User wants general conversation or Q&A

Return ONLY the intent name, nothing else."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    try:
        response = client.chat_with_retry(
            messages,
            temperature=0.3,
            max_tokens=10,
            node_name="router",
        )
        intent = response.content.strip().lower()

        # Validate the result
        valid_intents = {"github_search", "knowledge_query", "general_chat"}
        if intent not in valid_intents:
            logger.warning("Invalid intent from LLM: %s, defaulting to general_chat", intent)
            return "general_chat"

        logger.info("Intent classified by LLM: %s", intent)
        return intent

    except RuntimeError as e:
        logger.error("LLM classification failed: %s, defaulting to general_chat", e)
        return "general_chat"


# ---------------------------------------------------------------------------
# Intent Handlers
# ---------------------------------------------------------------------------


def handle_github_search(query: str) -> str:
    """Handle GitHub search intent.

    Searches GitHub for AI-related repositories matching the query.

    Args:
        query: Search query string.

    Returns:
        Search results formatted as a string.
    """
    logger.info("Handling GitHub search: %s", query)

    # Extract search terms from query
    search_terms = query.replace("github", "").replace("repo", "").strip()
    if not search_terms:
        search_terms = "AI LLM agent"

    # Build query with filters (topic filter is more reliable than language)
    # Common AI topics: ai, llm, agent, machine-learning, deep-learning, nlp
    search_query = f"{search_terms} topic:ai OR topic:llm OR topic:agent"
    
    # URL encode the search query
    encoded_query = urllib.parse.quote(search_query)

    try:
        url = f"{GITHUB_SEARCH_API}?q={encoded_query}&sort=stars&order=desc&per_page=5"
        logger.debug("GitHub API URL: %s", url)

        req = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        with urllib.request.urlopen(req, timeout=GITHUB_SEARCH_TIMEOUT) as response:
            data = json.loads(response.read().decode())

        if not data.get("items"):
            return "No repositories found matching your query."

        results = []
        for idx, repo in enumerate(data["items"][:5], 1):
            results.append(
                f"{idx}. **{repo['name']}** ({repo['stargazers_count']} stars)\n"
                f"   URL: {repo['html_url']}\n"
                f"   Description: {repo['description'] or 'N/A'}"
            )

        return "\n\n".join(results)

    except urllib.error.URLError as e:
        logger.error("GitHub API request failed: %s", e)
        return f"GitHub search failed: {e}"
    except json.JSONDecodeError as e:
        logger.error("Failed to parse GitHub API response: %s", e)
        return "Failed to parse GitHub search results."


def handle_knowledge_query(query: str) -> str:
    """Handle knowledge query intent.

    Searches the local knowledge base for relevant articles.

    Args:
        query: Search query string.

    Returns:
        Search results formatted as a string.
    """
    logger.info("Handling knowledge query: %s", query)

    if not KNOWLEDGE_BASE_PATH.exists():
        logger.warning("Knowledge base path does not exist: %s", KNOWLEDGE_BASE_PATH)
        return "Knowledge base not found."

    # Load all article files
    articles = []
    for article_file in KNOWLEDGE_BASE_PATH.glob("*.json"):
        # Skip analysis and processed files
        if "-analysis.json" in article_file.name or ".processed" in str(article_file):
            continue

        try:
            with open(article_file, encoding="utf-8") as f:
                article = json.load(f)
                articles.append(article)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to load article %s: %s", article_file, e)
            continue

    if not articles:
        return "No articles found in knowledge base."

    # Extract search keywords from query (split by common delimiters)
    keywords = []
    for part in query.split():
        if len(part) > 2:  # Only consider words longer than 2 chars
            keywords.append(part.lower())

    if not keywords:
        return f"Query '{query}' is too short. Please provide more keywords."

    # Score and rank articles
    matching_articles = []

    for article in articles:
        title = article.get("title", "")
        tags = article.get("tags", [])
        summary = article.get("summary", "")
        
        # Prepare text for search
        text_to_search = f"{title} {' '.join(tags)} {summary}".lower()

        # Calculate relevance score
        score = 0
        for keyword in keywords:
            if keyword in text_to_search:
                # Boost score for title matches
                if keyword in title.lower():
                    score += 10
                # Medium boost for tag matches
                elif any(keyword in tag.lower() for tag in tags):
                    score += 5
                # Lower boost for summary matches
                else:
                    score += 2

        if score > 0:
            matching_articles.append((score, article))

    # Sort by relevance score (descending)
    matching_articles.sort(key=lambda x: x[0], reverse=True)

    if not matching_articles:
        return f"No articles found matching '{query}'."

    results = []
    for idx, (score, article) in enumerate(matching_articles[:5], 1):
        title = article.get("title", "N/A")
        summary = article.get("summary", "N/A")
        
        # Truncate summary to first 150 chars to avoid too long output
        if len(summary) > 150:
            summary = summary[:150] + "..."
        
        source_url = article.get("source_url", "N/A")
        relevance = article.get("ai_analysis", {}).get("relevance_score", "N/A")

        results.append(
            f"{idx}. **{title}** (Relevance: {relevance}/10)\n"
            f"   Summary: {summary}\n"
            f"   URL: {source_url}"
        )

    return "\n\n".join(results)


def handle_general_chat(query: str) -> str:
    """Handle general chat intent.

    Uses LLM to answer general questions.

    Args:
        query: User question.

    Returns:
        LLM response.
    """
    logger.info("Handling general chat: %s", query)

    client = create_client()

    system_prompt = (
        "You are a helpful assistant specialized in AI, LLM, and agent technologies. "
        "Provide concise, informative answers in Chinese or English based on user language."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    try:
        response = client.chat_with_retry(
            messages,
            temperature=0.7,
            max_tokens=2048,
            node_name="router_chat",
        )
        return response.content

    except RuntimeError as e:
        logger.error("LLM response failed: %s", e)
        return f"Failed to generate response: {e}"


# ---------------------------------------------------------------------------
# Main Router
# ---------------------------------------------------------------------------


def route(query: str) -> str:
    """Route user query to appropriate handler.

    Two-layer classification:
    1. Try keyword matching (fast, zero cost)
    2. Fall back to LLM if unclear

    Args:
        query: User query string.

    Returns:
        Response string from the appropriate handler.
    """
    logger.info("Routing query: %s", query)

    # Layer 1: Keyword matching
    intent = detect_intent_by_keywords(query)

    # Layer 2: LLM classification fallback
    if intent is None:
        logger.debug("Keyword matching failed, using LLM classification")
        intent = classify_intent_with_llm(query)
    else:
        logger.debug("Intent detected by keyword: %s", intent)

    # Dispatch to handler
    handlers = {
        "github_search": handle_github_search,
        "knowledge_query": handle_knowledge_query,
        "general_chat": handle_general_chat,
    }

    handler = handlers.get(intent, handle_general_chat)
    response = handler(query)

    logger.info("Router response generated for intent: %s", intent)
    return response


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,  # Suppress detailed logs for cleaner output
        format="%(levelname)s: %(message)s",
    )

    test_queries = [
        ("github_search", "Show me trending OpenAI Python repositories"),
        ("knowledge_query", "Find articles about LLM fine-tuning"),
        ("general_chat", "What is the difference between supervised and unsupervised learning?"),
        ("knowledge_query", "Agent framework articles"),
        ("general_chat", "How do transformers work in NLP?"),
    ]

    print("=" * 70)
    print("Router Pattern Test - Intent Classification & Routing")
    print("=" * 70)

    for expected_intent, query in test_queries:
        print(f"\n[Query] {query}")
        print(f"Expected Intent: {expected_intent}")
        print("-" * 70)

        try:
            # Test keyword-based intent detection
            keyword_intent = detect_intent_by_keywords(query)
            print(f"Detected Intent (Keyword): {keyword_intent or 'None (will use LLM)'}")

            # Route and get response
            response = route(query)
            
            # Show response preview
            preview = response[:250]
            if len(response) > 250:
                preview += "..."
            
            print(f"Response:\n{preview}\n")

        except Exception as e:
            print(f"[Error] {e}\n")

    print("=" * 70)
    print("Test completed successfully!")
    print("=" * 70)
