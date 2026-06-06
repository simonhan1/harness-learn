"""Revise 节点：根据审核反馈调用 LLM 修正 analyses 中的知识条目。

读取 state["analyses"] 对应的分析文件，将条目与 review_feedback 一并
发送给 LLM（temperature=0.4），LLM 返回修正后的条目列表，
写回新的分析文件并更新 state["analyses"]。

analyses 或 feedback 为空时跳过，返回 {}。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from state import KBState
from nodes import accumulate_usage, _parse_json_response, _compute_cost, _now_iso, _today_str

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 将 pipeline/ 加入模块搜索路径，导入 model_client
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    """Locate the project root by searching upward for AGENTS.md."""
    candidates: list[Path] = []
    try:
        candidates.append(Path(__file__).resolve().parent.parent)
    except (NameError, OSError):
        pass
    candidates.append(Path.cwd().resolve())

    for start in candidates:
        probe = start
        for _ in range(6):
            if (probe / "AGENTS.md").is_file():
                return probe
            parent = probe.parent
            if parent == probe:
                break
            probe = parent

    return candidates[0]


_PROJECT_ROOT = _find_project_root()
_pipeline_dir = str(_PROJECT_ROOT / "pipeline")
if _pipeline_dir not in sys.path:
    sys.path.insert(0, _pipeline_dir)

from model_client import create_client  # noqa: E402

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

REVISE_SYSTEM_PROMPT = (
    "你是一个AI知识库内容编辑专家。请根据审核反馈精准修正知识条目，"
    "严格按JSON数组格式输出修正后的条目列表。不要输出任何其他文字。"
)

REVISE_USER_PROMPT_TEMPLATE = """根据以下审核反馈，修正所有知识条目。返回修正后的完整JSON数组。

审核反馈：
{feedback}

待修正条目：
{items_json}

请根据反馈修正每个条目的 summary、tags、category 或 relevance_score，
其他字段（id、source_url、source、collected_at、status、published_at）保持不变。
只输出JSON数组，不要任何其他文字或markdown代码块。"""

# 批量修正：每批最多处理的条目数，避免超过 LLM max_tokens 限制
MAX_REVISE_BATCH = 6


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
            logger.warning("[ReviseNode] Analysis file not found: %s", p)
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                items.extend(data)
                logger.info("[ReviseNode] Loaded %d items from %s", len(data), p.name)
            else:
                logger.warning("[ReviseNode] Unexpected format in %s: expected list", p.name)
        except Exception as e:
            logger.error("[ReviseNode] Failed to read %s: %s", p, e)
    return items


def _save_analysis_file(analysis: dict, items: list[dict]) -> str:
    """Save revised items to a new analysis file.

    Args:
        analysis: The original analysis summary dict.
        items: Revised article items.

    Returns:
        Path to the new analysis file.
    """
    project_root = _find_project_root()
    articles_dir = project_root / "knowledge" / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)

    source = analysis.get("source", "unknown")
    filename = f"{_today_str()}-{source}-analysis.json"
    file_path = articles_dir / filename

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    logger.info("[ReviseNode] Revised analysis saved to %s (%d items)", file_path, len(items))
    return str(file_path)


def _preserve_immutable_fields(original: dict, revised: dict) -> dict:
    """Ensure immutable fields are not altered by the LLM.

    Args:
        original: Original article dict.
        revised: LLM-revised article dict.

    Returns:
        Revised dict with immutable fields restored from original.
    """
    for key in ("id", "source_url", "source", "collected_at", "status", "published_at"):
        if key in original:
            revised[key] = original[key]
    return revised


# ---------------------------------------------------------------------------
# 修正节点
# ---------------------------------------------------------------------------


def revise_node(state: KBState) -> dict:
    """Revise analyses based on review feedback via LLM.

    Reads analysis files referenced in state["analyses"], sends all items
    together with the review_feedback to the LLM at temperature=0.4,
    writes the revised items back to new analysis files, and returns
    updated analyses summaries with cost tracking.

    Skips when analyses or feedback is empty (returns {}).

    Args:
        state: Current workflow state.

    Returns:
        Partial state update: {"analyses": [...], "cost_tracker": {...}}.
        Empty dict when skipped.
    """
    analyses: list[dict] = state.get("analyses", [])
    review_feedback: str = state.get("review_feedback", "")
    cost_tracker: dict = state.get("cost_tracker") or {}

    # 跳过空输入
    if not analyses:
        logger.info("[ReviseNode] Skipping: no analyses to revise")
        return {}
    if not review_feedback:
        logger.info("[ReviseNode] Skipping: no review feedback")
        return {}

    logger.info("[ReviseNode] Starting revision with feedback: %s", review_feedback[:100])

    # 加载全部条目
    all_items = _load_analysis_items(analyses)
    if not all_items:
        logger.warning("[ReviseNode] No items found in analysis files, skipping")
        return {}

    logger.info("[ReviseNode] Total items to revise: %d", len(all_items))

    # 创建 LLM 客户端
    try:
        client = create_client()
    except ValueError as e:
        logger.error("[ReviseNode] Failed to create LLM client: %s", e)
        return {}

    # 构建精简的条目列表供 LLM 修正
    items_for_llm = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "summary": item.get("summary"),
            "tags": item.get("tags"),
            "category": item.get("category"),
            "relevance_score": item.get("relevance_score"),
            "key_points": item.get("key_points"),
            "source_url": item.get("source_url"),
        }
        for item in all_items
    ]

    # --- 批量调用 LLM，避免单次 max_tokens 不够 ---
    revised_items: list[dict] = []
    batch_count = 0

    for batch_start in range(0, len(items_for_llm), MAX_REVISE_BATCH):
        batch = items_for_llm[batch_start:batch_start + MAX_REVISE_BATCH]
        batch_count += 1
        items_json = json.dumps(batch, ensure_ascii=False, indent=2)
        prompt = REVISE_USER_PROMPT_TEMPLATE.format(
            feedback=review_feedback,
            items_json=items_json,
        )

        logger.info(
            "[ReviseNode] Batch %d: revising items %d-%d/%d",
            batch_count, batch_start + 1,
            batch_start + len(batch), len(items_for_llm),
        )

        response = None
        try:
            messages = [
                {"role": "system", "content": REVISE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            response = client.chat_with_retry(messages, temperature=0.4, max_tokens=4096)
            batch_result = _parse_json_response(response.content)

            if not isinstance(batch_result, list):
                logger.error(
                    "[ReviseNode] Batch %d: LLM returned non-list: %s", batch_count, type(batch_result)
                )
                # 批次失败：保留原始条目，不阻塞整体流程
                revised_items.extend(batch)
                continue

            revised_items.extend(batch_result)
            accumulate_usage(cost_tracker, response.usage)
            logger.info(
                "[ReviseNode] Batch %d OK: %d items revised", batch_count, len(batch_result)
            )

        except Exception as e:
            preview = response.content[:200] if response else "(no response)"
            logger.error(
                "[ReviseNode] Batch %d LLM call failed: %s | preview: %s",
                batch_count, e, preview,
            )
            # 批次失败：保留原始条目
            revised_items.extend(batch)

    # 对齐长度并保留不可变字段
    if len(revised_items) != len(all_items):
        logger.warning(
            "[ReviseNode] Item count mismatch: original=%d, revised=%d",
            len(all_items), len(revised_items),
        )

    improved: list[dict] = []
    for i, original in enumerate(all_items):
        if i < len(revised_items):
            revised = _preserve_immutable_fields(original, revised_items[i])
            improved.append(revised)
        else:
            improved.append(original)

    # 按原始 analysis 分组并写回文件
    updated_analyses: list[dict] = []
    offset = 0
    for analysis in analyses:
        file_path = analysis.get("analysis_file", "")
        if not file_path:
            updated_analyses.append(analysis)
            continue

        p = Path(file_path)
        if not p.exists():
            updated_analyses.append(analysis)
            continue

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = len(data) if isinstance(data, list) else 0
        except Exception:
            count = 0

        batch = improved[offset:offset + count] if count > 0 else []
        offset += count

        new_file_path = _save_analysis_file(analysis, batch)

        updated_analyses.append({
            "analysis_id": analysis.get("analysis_id", f"unknown-{_today_str()}"),
            "source": analysis.get("source", "unknown"),
            "analyzed_count": analysis.get("analyzed_count", len(batch)),
            "success_count": len(batch),
            "failed_items": analysis.get("failed_items", []),
            "analysis_file": new_file_path,
            "analyzed_at": _now_iso(),
        })

    # 更新成本
    cost_tracker["estimated_cost_usd"] = _compute_cost(cost_tracker, client.provider)

    logger.info(
        "[ReviseNode] Revision complete: %d analyses updated, API calls=%d, cost=$%.6f",
        len(updated_analyses),
        cost_tracker.get("total_api_calls", 0),
        cost_tracker.get("estimated_cost_usd", 0.0),
    )

    return {
        "analyses": updated_analyses,
        "cost_tracker": cost_tracker,
    }
