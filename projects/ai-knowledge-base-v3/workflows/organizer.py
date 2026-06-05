"""Organizer 节点：最终整理入库——加载审核通过的 analyses，去重、过滤低分条目，
逐条保存为 knowledge/articles/YYYYMMDD-{source}-{slug}.json 并更新 index.json。

该节点为工作流正常终点（terminal node），返回空 dict。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from state import KBState
from nodes import (
    _ensure_dirs,
    _now_iso,
    _today_str,
    _slugify,
    ARTICLES_DIR,
    INDEX_FILE,
    RELEVANCE_MIN,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _load_analysis_items(analyses: list[dict]) -> list[dict]:
    """Read analysis files and collect article items.

    Args:
        analyses: List of analysis summary dicts from state["analyses"].

    Returns:
        Flattened list of article dicts from all analysis files.
    """
    items: list[dict] = []
    for analysis in analyses:
        file_path = analysis.get("analysis_file", "")
        if not file_path:
            continue
        p = Path(file_path)
        if not p.exists():
            logger.warning("[Organizer] Analysis file not found: %s", p)
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                items.extend(data)
                logger.info("[Organizer] Loaded %d items from %s", len(data), p.name)
            else:
                logger.warning("[Organizer] Unexpected format in %s: expected list", p.name)
        except Exception as e:
            logger.error("[Organizer] Failed to read %s: %s", p, e)
    return items


def _update_index(new_entries: list[dict]) -> None:
    """Merge new entries into knowledge/articles/index.json, dedup by id.

    Args:
        new_entries: List of lightweight index entry dicts.
    """
    existing_index: list[dict] = []
    if INDEX_FILE.exists():
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                existing_index = json.load(f)
        except Exception as e:
            logger.warning("[Organizer] Could not read existing index: %s", e)

    existing_ids = {e["id"] for e in existing_index}
    for entry in new_entries:
        if entry["id"] not in existing_ids:
            existing_index.append(entry)
            existing_ids.add(entry["id"])

    existing_index.sort(key=lambda x: x.get("saved_at", ""), reverse=True)

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_index, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 整理节点
# ---------------------------------------------------------------------------


def organize_node(state: KBState) -> dict:
    """Terminal node: load reviewed analyses, dedup, filter, save, update index.

    Steps:
        1. Load all article items from analysis files referenced in state["analyses"].
        2. Deduplicate by source_url.
        3. Filter out items with relevance_score < RELEVANCE_MIN.
        4. Save each remaining article as an individual JSON file.
        5. Merge into knowledge/articles/index.json.

    Args:
        state: Current workflow state (expected: review_passed == True).

    Returns:
        Empty dict (terminal node).
    """
    logger.info("[Organizer] Starting final organization and save")

    analyses: list[dict] = state.get("analyses", [])

    if not analyses:
        logger.warning("[Organizer] No analyses to organize, nothing to save")
        return {}

    # Step 1 — 从 analysis 文件加载全部条目
    all_items = _load_analysis_items(analyses)
    if not all_items:
        logger.warning("[Organizer] No items found in analysis files")
        return {}

    logger.info("[Organizer] Loaded %d total items from %d analyses", len(all_items), len(analyses))

    # Step 2 — URL 去重
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for article in all_items:
        url = article.get("source_url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped.append(article)
        elif not url:
            deduped.append(article)
        else:
            logger.info("[Organizer] Duplicate removed: %s", article.get("title", ""))

    logger.info("[Organizer] Dedup: %d → %d", len(all_items), len(deduped))

    # Step 3 — 过滤低分条目
    relevance_threshold = RELEVANCE_MIN
    plan: dict = state.get("plan") or {}
    if plan_relevance := plan.get("relevance_threshold"):
        # plan 中的 relevance_threshold 是 0-1 制，转换为 1-10 制
        relevance_threshold = max(1, min(10, int(plan_relevance * 10)))

    filtered: list[dict] = [
        a for a in deduped if a.get("relevance_score", 0) >= relevance_threshold
    ]
    logger.info(
        "[Organizer] Relevance filter (>=%d): %d → %d",
        relevance_threshold, len(deduped), len(filtered),
    )

    if not filtered:
        logger.warning("[Organizer] No articles passed relevance filter")
        return {}

    # Step 4 — 保存每个条目为独立 JSON 文件
    _ensure_dirs()

    new_entries: list[dict] = []
    saved_count = 0

    for article in filtered:
        try:
            article_id = article.get("id", f"unknown-{saved_count:03d}")
            slug = _slugify(article.get("title", article_id))
            source = article.get("source", "unknown")
            filename = f"{_today_str()}-{source}-{slug}.json"
            article_file = ARTICLES_DIR / filename

            with open(article_file, "w", encoding="utf-8") as f:
                json.dump(article, f, ensure_ascii=False, indent=2)

            new_entries.append({
                "id": article_id,
                "title": article.get("title", ""),
                "source": source,
                "category": article.get("category", ""),
                "relevance_score": article.get("relevance_score", 0),
                "status": article.get("status", "draft"),
                "file": filename,
                "saved_at": _now_iso(),
            })
            saved_count += 1
            logger.info("[Organizer] Saved: %s → %s", article_id, filename)

        except Exception as e:
            logger.error(
                "[Organizer] Failed to save article %s: %s", article.get("id", "?"), e
            )

    # Step 5 — 更新 index.json
    _update_index(new_entries)

    logger.info(
        "[Organizer] Complete: %d articles saved, index updated", saved_count,
    )
    return {}
