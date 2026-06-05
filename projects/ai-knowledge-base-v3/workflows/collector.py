"""Collector 节点：从 GitHub Search API 采集 AI 相关 Trending 仓库。

输出写入 knowledge/raw/github_trending_{timestamp}.json，
返回 state["sources"] 摘要列表供下游分析使用。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any
from pathlib import Path

import httpx
from dotenv import load_dotenv

from state import KBState
from nodes import (
    _ensure_dirs,
    _now_iso,
    AI_KEYWORDS_RE,
    CST,
    RAW_DIR,
)

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_TIMEOUT = 30.0
GITHUB_PER_PAGE = 30


# ---------------------------------------------------------------------------
# 采集节点
# ---------------------------------------------------------------------------


def collect_node(state: KBState) -> dict:
    """Collect AI-related trending repos from GitHub Search API.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update: {"sources": [...]}.
    """
    logger.info("[Collector] Starting GitHub trending data collection")

    _ensure_dirs()

    params: dict[str, str | int] = {
        "q": "ai OR llm OR agent OR gpt OR openai topics:>=1",
        "sort": "stars",
        "order": "desc",
        "per_page": GITHUB_PER_PAGE,
    }
    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    if token := os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    collected_items: list[dict[str, Any]] = []

    try:
        logger.info("[Collector] Fetching GitHub Search API: q=%s", params["q"])
        resp = httpx.get(
            GITHUB_SEARCH_URL,
            params=params,
            headers=headers,
            timeout=GITHUB_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", [])[:GITHUB_PER_PAGE]:
            desc = item.get("description") or ""
            topics = item.get("topics") or []
            if AI_KEYWORDS_RE.search(f"{desc} {' '.join(topics)}"):
                collected_items.append({
                    "name": item["full_name"],
                    "url": item["html_url"],
                    "description": desc,
                    "stars": item["stargazers_count"],
                    "language": item.get("language") or "",
                    "topics": topics,
                })

        logger.info("[Collector] Collected %d AI-related items", len(collected_items))

        ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
        raw_file = RAW_DIR / f"github_trending_{ts}.json"
        with open(raw_file, "w", encoding="utf-8") as f:
            json.dump(
                {"source": "github_trending", "collected_at": _now_iso(), "items": collected_items},
                f, ensure_ascii=False, indent=2,
            )
        logger.info("[Collector] Raw data saved to %s", raw_file)

        return {
            "sources": [
                {
                    "source": "github_trending",
                    "collected_at": _now_iso(),
                    "count": len(collected_items),
                    "file_path": str(raw_file),
                }
            ]
        }

    except Exception as e:
        logger.error("[Collector] Collection failed: %s", e, exc_info=True)
        return {"sources": []}
