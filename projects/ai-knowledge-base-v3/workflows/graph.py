"""LangGraph 工作流组装：规划 → 采集 → 分析 → 审核 → 整理/修正。

build_graph() 返回编译后的 LangGraph app，可直接调用 .invoke() 或 .stream()。

工作流拓扑：
                       ┌───[pass]────→ organize → END
    planner → collector → analyzer → reviewer ──[fail < max]──→ revise → reviewer（循环）
                       │
                       └───[>= max]───→ human_flag → END
"""

from __future__ import annotations

import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from state import KBState
from collector import collect_node
from analyzer import analyze_node
from organizer import organize_node
from reviewer import review_node
from reviser import revise_node
from human_flag import human_flag_node
from planner import planner_node

logger = logging.getLogger(__name__)

# 最大审核迭代次数：超过此值仍未通过则路由到 human_flag 节点
MAX_ITERATIONS = 3


# ---------------------------------------------------------------------------
# 条件路由函数
# ---------------------------------------------------------------------------


def _review_router(state: KBState) -> Literal["organize", "revise", "human_flag"]:
    """根据审核结果决定下一个节点。

    三路分支：
    - 审核通过 → 整理入库节点
    - 审核未通过但未超迭代上限 → 修正节点（修正后回到 reviewer 重新审核）
    - 审核未通过且已达迭代上限 → 人工标记节点

    Args:
        state: 当前工作流状态。

    Returns:
        "organize" / "revise" / "human_flag" 三选一。
    """
    if state.get("review_passed", False):
        logger.info("[Router] Review passed → organize")
        return "organize"

    iteration = state.get("iteration", 0)
    plan: dict = state.get("plan") or {}
    max_iter = plan.get("max_iterations", MAX_ITERATIONS)

    if iteration >= max_iter:
        logger.warning(
            "[Router] Review not passed and iteration=%d >= max=%d → human_flag",
            iteration, max_iter,
        )
        return "human_flag"

    logger.info(
        "[Router] Review not passed (iteration=%d < max=%d) → revise", iteration, max_iter,
    )
    return "revise"


# ---------------------------------------------------------------------------
# 图组装
# ---------------------------------------------------------------------------


def build_graph():
    """组装并编译 LangGraph 工作流。

    Returns:
        编译后的 LangGraph app（CompiledStateGraph），
        可调用 .invoke(initial_state) 或 .stream(initial_state)。
    """
    graph: StateGraph = StateGraph(KBState)

    # --- 注册节点 ---
    graph.add_node("planner", planner_node)
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("review", review_node)
    graph.add_node("revise", revise_node)
    graph.add_node("organize", organize_node)
    graph.add_node("human_flag", human_flag_node)

    # --- 线性边 ---
    graph.add_edge("planner", "collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "review")

    # --- 条件边：review → organize / revise / human_flag ---
    graph.add_conditional_edges(
        "review",
        _review_router,
        {
            "organize": "organize",
            "revise": "revise",
            "human_flag": "human_flag",
        },
    )

    # --- revise → review（修正后重新审核）---
    graph.add_edge("revise", "review")

    # --- 终止边 ---
    graph.add_edge("organize", END)
    graph.add_edge("human_flag", END)

    # --- 入口点 ---
    graph.set_entry_point("planner")

    return graph.compile()


# ---------------------------------------------------------------------------
# 调试入口：流式执行并打印每个节点的关键输出
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    app = build_graph()
    logger.info("LangGraph 工作流已编译，开始流式执行...")

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
            "model_used": "",
            "estimated_cost_usd": 0.0,
            "calls_by_node": {},
        },
        "needs_human_review": False,
    }

    for step in app.stream(initial_state):
        for node_name, output in step.items():
            if output is None:
                output = {}
            logger.info("─── 节点完成: %-10s ───────────────────────────", node_name)

            if node_name == "planner":
                plan = output.get("plan", {})
                logger.info(
                    "策略: tier=%s  target=%d  per_source=%d",
                    plan.get("tier", "?"),
                    plan.get("target_count", 0),
                    plan.get("per_source_limit", 0),
                )

            elif node_name == "collect":
                sources = output.get("sources", [])
                logger.info("采集到 %d 个来源", len(sources))
                for src in sources:
                    logger.info(
                        "  · %s  %d 条  →  %s",
                        src.get("source", "?"),
                        src.get("count", 0),
                        src.get("file_path", ""),
                    )

            elif node_name == "analyze":
                articles = output.get("articles", [])
                cost = output.get("cost_tracker", {})
                logger.info(
                    "分析完成: %d 篇文章  |  API 调用 %d 次  |  估算费用 $%.4f",
                    len(articles),
                    cost.get("total_api_calls", 0),
                    cost.get("estimated_cost_usd", 0.0),
                )

            elif node_name == "review":
                passed = output.get("review_passed", False)
                feedback = output.get("review_feedback", "")
                iteration = output.get("iteration", 0)
                logger.info(
                    "审核结果: %s  （第 %d 轮）",
                    "✓ 通过" if passed else "✗ 未通过",
                    iteration,
                )
                if feedback:
                    logger.info("审核意见: %s", feedback[:300])

            elif node_name == "revise":
                analyses = output.get("analyses", [])
                cost = output.get("cost_tracker", {})
                logger.info(
                    "修正完成: %d 个分析文件  |  API 调用 %d 次",
                    len(analyses),
                    cost.get("total_api_calls", 0),
                )

            elif node_name == "organize":
                logger.info("整理入库完成（去重、过滤、保存、更新索引）")

            elif node_name == "human_flag":
                needs = output.get("needs_human_review", False)
                logger.warning(
                    "⚠ 人工标记: needs_human_review=%s  (数据已写入 knowledge/pending_review/)",
                    needs,
                )

    logger.info("═══════════════ 工作流执行完毕 ═══════════════")
