"""Planner 节点：根据目标采集量选择策略，产出 dict 写入 state.plan。

在采集阶段之前执行，分析 target_count 决定采用 lite / standard / full 三档策略，
各档影响每源采集上限、相关性阈值和最大审核迭代次数。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from state import KBState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_TARGET_COUNT = 10

STRATEGY_RATIONALE: dict[str, str] = {
    "lite": "轻量模式：目标采集量较少，收紧每源采集上限和相关性阈值，减少 API 调用和审核轮次",
    "standard": "标准模式：平衡采集深度与效率，适应常规日常监控场景",
    "full": "全面模式：最大化采集量，放宽相关性阈值，允许多轮审核迭代以确保覆盖度",
}


# ---------------------------------------------------------------------------
# 策略函数
# ---------------------------------------------------------------------------


def plan_strategy(target_count: int | None = None) -> dict[str, Any]:
    """根据目标采集量返回三档策略 dict。

    Args:
        target_count: 目标采集条目数。None 时从环境变量 PLANNER_TARGET_COUNT 读取，
                      默认 10。

    Returns:
        策略 dict，包含以下字段：
        - tier (str): 策略档位 "lite" / "standard" / "full"
        - target_count (int): 实际使用的目标采集量
        - per_source_limit (int): 每源采集上限
        - relevance_threshold (float): 相关性阈值（0-1 制）
        - max_iterations (int): 最大审核迭代次数
        - rationale (str): 选择该策略的理由说明
    """
    if target_count is None:
        raw = os.getenv("PLANNER_TARGET_COUNT", str(DEFAULT_TARGET_COUNT))
        try:
            target_count = int(raw)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid PLANNER_TARGET_COUNT=%r, using default %d", raw, DEFAULT_TARGET_COUNT
            )
            target_count = DEFAULT_TARGET_COUNT
    else:
        target_count = int(target_count)

    if target_count < 10:
        tier = "lite"
        per_source_limit = 5
        relevance_threshold = 0.7
        max_iterations = 1
    elif 10 <= target_count < 20:
        tier = "standard"
        per_source_limit = 10
        relevance_threshold = 0.5
        max_iterations = 2
    else:
        tier = "full"
        per_source_limit = 20
        relevance_threshold = 0.4
        max_iterations = 3

    plan: dict[str, Any] = {
        "tier": tier,
        "target_count": target_count,
        "per_source_limit": per_source_limit,
        "relevance_threshold": relevance_threshold,
        "max_iterations": max_iterations,
        "rationale": STRATEGY_RATIONALE[tier],
    }

    logger.info(
        "[Planner] Strategy selected: tier=%s, target=%d, per_source_limit=%d, "
        "relevance_threshold=%.1f, max_iterations=%d",
        tier, target_count, per_source_limit, relevance_threshold, max_iterations,
    )

    return plan


# ---------------------------------------------------------------------------
# LangGraph 节点
# ---------------------------------------------------------------------------


def planner_node(state: KBState) -> dict[str, Any]:
    """LangGraph 节点包装：调用 plan_strategy 生成采集策略。

    从 state 中的 plan 或环境变量读取 target_count，产出策略 dict
    写入 state.plan。若 state 中已有有效 plan 则复用，避免重复计算。

    Args:
        state: 当前工作流状态。

    Returns:
        Partial state update: {"plan": {...}}。
    """
    existing_plan: dict = state.get("plan") or {}

    # 若已有有效策略（含 tier），直接复用
    if existing_plan and existing_plan.get("tier"):
        logger.info("[PlannerNode] Reusing existing plan: tier=%s", existing_plan["tier"])
        return {"plan": existing_plan}

    target_count_raw: Any = existing_plan.get("target_count") if existing_plan else None
    try:
        target_count = int(target_count_raw) if target_count_raw is not None else None
    except (ValueError, TypeError):
        target_count = None

    plan = plan_strategy(target_count)
    return {"plan": plan}
