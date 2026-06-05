"""HumanFlag 节点：超过 max_iterations 仍未通过审核时，标记需要人工介入。

当 workflow 审核循环次数超过配置阈值仍未通过时，说明内容质量存疑，
不应继续耗费 token 进行自动修正。该节点将问题条目归档到
knowledge/pending_review/ 独立目录，不污染主知识库。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from state import KBState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

CST = timezone(timedelta(hours=8))

# max_iterations：审核循环的最大迭代次数，超过此值仍未通过则触发人工标记
# 若调用时未显式传入，则使用此默认值
DEFAULT_MAX_ITERATIONS = 3


# ---------------------------------------------------------------------------
# 工具函数
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
_PENDING_DIR = _PROJECT_ROOT / "knowledge" / "pending_review"


def _now_iso() -> str:
    """Return current time in ISO 8601 with CST offset."""
    return datetime.now(CST).isoformat()


def _today_str() -> str:
    """Return today's date as YYYYMMDD in CST."""
    return datetime.now(CST).strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# 人工标记节点
# ---------------------------------------------------------------------------


def human_flag_node(
    state: KBState,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> dict[str, Any]:
    """超出最大迭代次数仍审核未通过时，标记问题条目供人工复盘。

    当 state["iteration"] >= max_iterations 且 review_passed 为 False 时，
    将当前全部 articles / analyses / feedback 写入
    knowledge/pending_review/pending-{today}.json，返回
    needs_human_review=True。否则跳过，返回 needs_human_review=False。

    Args:
        state: 当前工作流状态，包含 iteration / review_passed / articles 等。
        max_iterations: 允许的最大审核迭代次数，默认 3。

    Returns:
        Partial state update: {"needs_human_review": bool}。
    """
    iteration: int = state.get("iteration", 0)
    review_passed: bool = state.get("review_passed", False)
    articles: list[dict] = state.get("articles", [])
    analyses: list[dict] = state.get("analyses", [])
    review_feedback: str = state.get("review_feedback", "")

    logger.info(
        "[HumanFlagNode] Checking: iteration=%d/%d, passed=%s, articles=%d",
        iteration, max_iterations, review_passed, len(articles),
    )

    # 审核已通过或未超迭代次数，无需人工介入
    if review_passed:
        logger.info("[HumanFlagNode] Review already passed, no human review needed")
        return {"needs_human_review": False}

    if iteration < max_iterations:
        logger.info(
            "[HumanFlagNode] iteration=%d < max=%d, still within retry budget",
            iteration, max_iterations,
        )
        return {"needs_human_review": False}

    # iteration >= max_iterations 且未通过 → 需要人工介入
    logger.warning(
        "[HumanFlagNode] Max iterations (%d) exceeded without passing review. "
        "Flagging %d articles + %d analyses for human review.",
        max_iterations, len(articles), len(analyses),
    )

    _PENDING_DIR.mkdir(parents=True, exist_ok=True)

    pending_data: dict[str, Any] = {
        "timestamp": _now_iso(),
        "iterations_used": iteration,
        "max_iterations": max_iterations,
        "last_feedback": review_feedback,
        "analyses": analyses,
        "articles": articles,
    }

    filename = f"pending-{_today_str()}.json"
    filepath = _PENDING_DIR / filename

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, ensure_ascii=False, indent=2)
        logger.info(
            "[HumanFlagNode] Pending review data saved to %s (%d articles, %d analyses)",
            filepath, len(articles), len(analyses),
        )
    except OSError as e:
        logger.error("[HumanFlagNode] Failed to write pending review file: %s", e)

    return {"needs_human_review": True}
