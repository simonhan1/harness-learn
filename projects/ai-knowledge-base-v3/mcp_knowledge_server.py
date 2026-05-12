#!/usr/bin/env python3
"""MCP Knowledge Server — search local AI knowledge base via stdio JSON-RPC 2.0."""

import json
import logging
import sys
from pathlib import Path

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ARTICLES_DIR = Path(__file__).resolve().parent / "knowledge" / "articles"

_cache = None
_cache_mtime = 0.0


def _latest_mtime():
    """Return the latest mtime among all JSON files under articles/."""
    latest = 0.0
    for fpath in ARTICLES_DIR.rglob("*.json"):
        if ".processed" in fpath.parts:
            continue
        try:
            mtime = fpath.stat().st_mtime
            if mtime > latest:
                latest = mtime
        except OSError:
            continue
    return latest


def load_all_articles():
    """Load all articles from knowledge/articles/ (skipping .processed/)."""
    articles = {}
    for fpath in sorted(ARTICLES_DIR.rglob("*.json")):
        if ".processed" in fpath.parts:
            continue
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict) or "id" not in item:
                continue
            articles[item["id"]] = item
    return articles


def get_articles():
    """Return cached articles, reload if any file has changed on disk."""
    global _cache, _cache_mtime
    latest = _latest_mtime()
    if latest > _cache_mtime:
        logger.info("Reloading articles (detected file changes)")
        _cache = load_all_articles()
        _cache_mtime = latest
        logger.info("Loaded %d articles", len(_cache))
    return _cache


def search_articles(articles, keyword, limit=5):
    """Search by keyword in title and summary."""
    kw = keyword.lower()
    results = []
    for art in articles.values():
        if kw in art.get("title", "").lower() or kw in art.get("summary", "").lower():
            results.append({
                "id": art["id"],
                "title": art.get("title"),
                "source": art.get("source"),
                "summary": art.get("summary"),
                "category": art.get("category"),
                "tags": art.get("tags", []),
                "relevance_score": art.get("ai_analysis", {}).get("relevance_score"),
                "status": art.get("status"),
            })
    results.sort(key=lambda x: x.get("relevance_score") or 0, reverse=True)
    return results[:limit]


def get_article(articles, article_id):
    """Get full article by ID."""
    art = articles.get(article_id)
    if art is None:
        return {"error": f"Article '{article_id}' not found"}
    return art


def knowledge_stats(articles):
    """Return statistics about the knowledge base."""
    total = len(articles)
    sources = {}
    all_tags = {}
    categories = {}
    for art in articles.values():
        src = art.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1
        for tag in art.get("tags", []):
            all_tags[tag] = all_tags.get(tag, 0) + 1
        cat = art.get("category", "uncategorized")
        categories[cat] = categories.get(cat, 0) + 1
    top_tags = sorted(all_tags.items(), key=lambda x: -x[1])[:10]
    return {
        "total_articles": total,
        "sources": sources,
        "categories": categories,
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
    }


TOOLS = [
    {
        "name": "search_articles",
        "description": "Search knowledge articles by keyword in title and summary",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Search keyword"},
                "limit": {"type": "integer", "description": "Max results (default 5)", "default": 5},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_article",
        "description": "Get full article content by ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {"type": "string", "description": "Article ID (e.g. github-20260510-012)"},
            },
            "required": ["article_id"],
        },
    },
    {
        "name": "knowledge_stats",
        "description": "Return statistics about the knowledge base (total articles, source distribution, top tags)",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def main():
    logger.info("MCP Knowledge Server starting, articles dir: %s", ARTICLES_DIR)
    get_articles()  # warm up cache

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": "mcp-knowledge-server",
                        "version": "1.0.0",
                    },
                },
            }
        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS},
            }
        elif method == "tools/call":
            articles = get_articles()
            tool_name = params.get("name")
            args = params.get("arguments", {})
            if tool_name == "search_articles":
                result = search_articles(articles, args["keyword"], args.get("limit", 5))
            elif tool_name == "get_article":
                result = get_article(articles, args["article_id"])
            elif tool_name == "knowledge_stats":
                result = knowledge_stats(articles)
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                }
                _write(resp)
                continue

            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]},
            }
        elif method == "notifications/initialized":
            continue
        else:
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        _write(resp)


def _write(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
