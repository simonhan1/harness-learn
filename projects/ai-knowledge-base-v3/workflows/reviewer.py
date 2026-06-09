"""Reviewer 节点：对 analyses 进行 5 维度评分审核。

审核对象为 state["analyses"]（而非 articles），读取分析文件内容，
取前 5 条交由 LLM 评分（temperature=0.1），代码重算加权总分。

5 维度权重：
    summary_quality  25%
    technical_depth  25%
    relevance        20%
    originality      15%
    formatting       15%

加权总分 >= 7.0 为通过；LLM 调用失败时自动通过（不阻塞流程）。
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from state import KBState
from nodes import accumulate_usage, _parse_json_response, _compute_cost

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

DIMENSION_WEIGHTS: dict[str, float] = {
    "summary_quality": 0.25,
    "technical_depth": 0.25,
    "relevance": 0.20,
    "originality": 0.15,
    "formatting": 0.15,
}

MAX_REVIEW_ITEMS = 5
PASS_THRESHOLD = 9.0

REVIEW_SYSTEM_PROMPT = (
    "你是一个AI知识库内容审核专家。请严格按JSON格式输出审核结果，"
    "包含5个维度的评分（每维1-10分，整数）。不要输出任何其他文字。"
)

REVIEW_USER_PROMPT_TEMPLATE = """请对以下AI知识库的分析条目进行5维度评分（每维1-10分，整数）。

维度说明：
1. summary_quality（摘要质量）：摘要是否准确、完整、清晰地概括了核心内容
2. technical_depth（技术深度）：分析是否触及技术原理、架构设计或算法细节
3. relevance（相关性）：内容与AI/LLM/Agent领域的相关程度
4. originality（原创性）：项目的独创性、新颖性或对已有工作的改进程度
5. formatting（格式规范）：标签是否准确、分类是否合理、输出结构是否规范

待审核条目：
{articles_json}

请输出一个JSON对象（不要markdown代码块）：
{{
  "feedback": "中文审核意见（指出优点和需改进之处，200字以内）",
  "scores": {{
    "summary_quality": 8,
    "technical_depth": 7,
    "relevance": 9,
    "originality": 6,
    "formatting": 8
  }}
}}"""


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
            logger.warning("[Reviewer] Analysis file not found: %s", p)
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                items.extend(data)
                logger.info("[Reviewer] Loaded %d items from %s", len(data), p.name)
            else:
                logger.warning("[Reviewer] Unexpected format in %s: expected list", p.name)
        except Exception as e:
            logger.error("[Reviewer] Failed to read %s: %s", p, e)
    return items


def _validate_scores(scores: dict) -> dict[str, int]:
    """Clamp and validate dimension scores.

    Args:
        scores: Raw scores dict from LLM response.

    Returns:
        Dict with all 5 dimensions clamped to 1-10 integers.
    """
    validated: dict[str, int] = {}
    for dim, weight in DIMENSION_WEIGHTS.items():
        raw = scores.get(dim, 5)
        try:
            val = int(raw)
        except (ValueError, TypeError):
            val = 5
        validated[dim] = max(1, min(10, val))
    return validated


def _calc_weighted_score(scores: dict[str, int]) -> float:
    """Calculate weighted total score from dimension scores.

    Args:
        scores: Dimension scores dict (already validated to 1-10).

    Returns:
        Weighted total score, rounded to 2 decimal places.
    """
    total = sum(scores[dim] * weight for dim, weight in DIMENSION_WEIGHTS.items())
    return round(total, 2)


# ---------------------------------------------------------------------------
# 审核节点
# ---------------------------------------------------------------------------


def review_node(state: KBState) -> dict:
    """Review analyses with 5-dimension LLM scoring and code-verified weighted total.

    Reads analysis files from state["analyses"], takes the first 5 items,
    sends them to the LLM for dimension scoring, then recalculates the
    weighted total in Python code (do not trust model arithmetic).

    Pass threshold: weighted score >= 7.0.
    LLM failure → auto pass (do not block the pipeline).
    iteration >= 2 → force pass (prevent infinite loops).

    Args:
        state: Current workflow state.

    Returns:
        Partial state update: {"review_passed": bool, "review_feedback": str,
                               "iteration": int, "cost_tracker": {...}}.
    """
    iteration = state.get("iteration", 0)
    analyses: list[dict] = state.get("analyses", [])
    cost_tracker: dict = state.get("cost_tracker") or {}
    plan: dict = state.get("plan") or {}
    max_iter = plan.get("max_iterations") or 2

    logger.info("[Reviewer] Starting review (iteration=%d, max=%d)", iteration, max_iter)

    # 无 analyses → 自动通过
    if not analyses:
        logger.warning("[Reviewer] No analyses to review, auto-passing")
        return {
            "review_passed": True,
            "review_feedback": "No analyses available (auto-pass).",
            "iteration": iteration + 1,
            "cost_tracker": cost_tracker,
        }

    # iteration >= max_iter → 强制通过，避免无限循环
    if iteration >= max_iter:
        logger.info("[Reviewer] iteration=%d >= max=%d: forcing pass", iteration, max_iter)
        return {
            "review_passed": True,
            "review_feedback": "Force-passed after reaching max iterations.",
            "iteration": iteration + 1,
            "cost_tracker": cost_tracker,
        }

    # 加载 analysis 文件中的条目，取前 MAX_REVIEW_ITEMS 条
    all_items = _load_analysis_items(analyses)
    if not all_items:
        logger.warning("[Reviewer] No items found in analysis files, auto-passing")
        return {
            "review_passed": True,
            "review_feedback": "No items in analysis files (auto-pass).",
            "iteration": iteration + 1,
            "cost_tracker": cost_tracker,
        }

    review_items = all_items[:MAX_REVIEW_ITEMS]
    logger.info("[Reviewer] Reviewing %d items (total available: %d)", len(review_items), len(all_items))

    # 构建精简的条目列表供 LLM 审核
    items_for_llm = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "summary": item.get("summary"),
            "tags": item.get("tags"),
            "category": item.get("category"),
            "relevance_score": item.get("relevance_score"),
            "key_points": item.get("key_points"),
        }
        for item in review_items
    ]

    articles_json = json.dumps(items_for_llm, ensure_ascii=False, indent=2)
    prompt = REVIEW_USER_PROMPT_TEMPLATE.format(articles_json=articles_json)

    # 创建 LLM 客户端
    try:
        client = create_client()
    except ValueError as e:
        logger.error("[Reviewer] Failed to create LLM client: %s", e)
        return {
            "review_passed": True,
            "review_feedback": f"LLM client error (auto-pass): {e}",
            "iteration": iteration + 1,
            "cost_tracker": cost_tracker,
        }

    # 调用 LLM 评分（temperature=0.1 保证评分一致性）
    try:
        messages = [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        response = client.chat_with_retry(messages, temperature=0.1, max_tokens=1000, node_name="reviewer")
        review_result = _parse_json_response(response.content)

        feedback: str = str(review_result.get("feedback", ""))
        raw_scores: dict = review_result.get("scores", {})

        # 验证并钳位各维度分数
        scores = _validate_scores(raw_scores)

        # 用代码重算加权总分（不信任模型算术）
        weighted_score = _calc_weighted_score(scores)
        passed = weighted_score >= PASS_THRESHOLD

        # 累加 token 用量
        accumulate_usage(cost_tracker, response.usage)
        cost_tracker["estimated_cost_usd"] = _compute_cost(cost_tracker, client.provider)

        logger.info(
            "[Reviewer] Result: passed=%s, weighted_score=%.2f, scores=%s",
            passed, weighted_score, scores,
        )
        logger.info("[Reviewer] Feedback: %s", feedback[:200])

        return {
            "review_passed": passed,
            "review_feedback": feedback,
            "iteration": iteration + 1,
            "cost_tracker": cost_tracker,
        }

    except Exception as e:
        logger.error("[Reviewer] LLM call failed, auto-passing: %s", e)
        return {
            "review_passed": True,
            "review_feedback": f"Review error (auto-pass): {e}",
            "iteration": iteration + 1,
            "cost_tracker": cost_tracker,
        }
