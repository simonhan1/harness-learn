"""LangGraph 工作流组装：采集 → 分析 → 整理 → 审核 → 保存。

build_graph() 返回编译后的 LangGraph app，可直接调用 .invoke() 或 .stream()。

工作流拓扑：
    collect → analyze → organize → review ──(通过)──→ save → END
                                      ↑                       |
                                      └──────(未通过)──────────┘
"""

from __future__ import annotations

import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from state import KBState
from nodes import (
    collect_node,
    analyze_node,
    organize_node,
    review_node,
    save_node,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 条件路由函数
# ---------------------------------------------------------------------------


def _review_router(state: KBState) -> Literal["save", "organize"]:
    """根据审核结果决定下一个节点。

    Args:
        state: 当前工作流状态。

    Returns:
        "save" 如果审核通过，否则 "organize"（回到整理节点修正）。
    """
    if state.get("review_passed", False):
        logger.info("审核通过，进入保存节点")
        return "save"
    logger.info(
        "审核未通过（iteration=%d），回到整理节点修正",
        state.get("iteration", 0),
    )
    return "organize"


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
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("save", save_node)

    # --- 线性边 ---
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")

    # --- 条件边：review → save（通过）或 review → organize（未通过，回修正）---
    graph.add_conditional_edges(
        "review",
        _review_router,
        {
            "save": "save",
            "organize": "organize",
        },
    )

    # --- 终止边 ---
    graph.add_edge("save", END)

    # --- 入口点 ---
    graph.set_entry_point("collect")

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
    }

    for step in app.stream(initial_state):
        for node_name, output in step.items():
            logger.info("─── 节点完成: %-10s ───────────────────────────", node_name)

            if node_name == "collect":
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

            elif node_name == "organize":
                articles = output.get("articles", [])
                logger.info("整理后保留 %d 篇文章（已去重 + 评分过滤）", len(articles))
                for article in articles[:5]:
                    logger.info(
                        "  [%.0f/10] %-40s  %s",
                        article.get("relevance_score", 0),
                        article.get("title", "")[:40],
                        article.get("category", ""),
                    )
                if len(articles) > 5:
                    logger.info("  ... 共 %d 篇（仅显示前 5 条）", len(articles))

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

            elif node_name == "save":
                logger.info("全部文章已写入 knowledge/articles/，index.json 已更新")

    logger.info("═══════════════ 工作流执行完毕 ═══════════════")
