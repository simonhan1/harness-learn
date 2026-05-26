"""LangGraph 工作流的共享状态定义模块。

定义了 KBState TypedDict，用于在工作流节点间传递结构化数据。
遵循"报告式通信"原则：字段是结构化摘要，不是原始数据。
"""

from typing import TypedDict


class KBState(TypedDict):
    """AI 知识库工作流的共享状态。

    该状态贯穿整个"采集 → 分析 → 审核 → 分发"工作流，
    记录各阶段的中间结果和元数据。

    Attributes:
        sources (list[dict]): 采集阶段的原始数据摘要
            - 内容：各源采集到的原始数据列表
            - 格式示例：
              [
                {
                  "source": "github_trending",
                  "collected_at": "2026-04-28T10:30:00+08:00",
                  "count": 25,
                  "file_path": "knowledge/raw/github_trending_20260428_103000.json"
                },
                ...
              ]
            - 用途：追踪数据来源、采集时间和数据量，用于后续分析的输入定位

        analyses (list[dict]): 分析阶段的 LLM 分析结果摘要
            - 内容：AI 分析后的结构化摘要（不包含原始文本）
            - 格式示例：
              [
                {
                  "analysis_id": "github-20260428-001",
                  "source": "github_trending",
                  "analyzed_count": 25,
                  "success_count": 24,
                  "failed_items": [{"title": "xxx", "error": "API timeout"}],
                  "analysis_file": "knowledge/articles/20260428-github-analysis.json",
                  "analyzed_at": "2026-04-28T11:00:00+08:00"
                }
              ]
            - 用途：汇总分析结果的统计信息，包括成功率和失败详情

        articles (list[dict]): 格式化、去重、评分后的知识条目摘要
            - 内容：最终生成的标准知识条目列表（摘要级别）
            - 格式示例：
              [
                {
                  "id": "github-20260428-001",
                  "title": "OpenAI 发布 GPT-5 重大更新",
                  "source": "github_trending",
                  "category": "model_release",
                  "relevance_score": 9,
                  "status": "draft",
                  "article_file": "knowledge/articles/20260428-github-openai-gpt5.json"
                },
                ...
              ]
            - 用途：为审核节点提供可读的摘要列表，不包含完整内容

        review_feedback (str): 审核人员的反馈意见
            - 内容：针对本轮审核的意见和改进建议
            - 格式：自由文本
            - 示例：
              "条目1-5质量良好，建议发布。条目6-8相关性不足（得分<5），建议过滤。请修正条目9的分类。"
            - 用途：记录审核意见，指导修正方向

        review_passed (bool): 本轮审核是否通过
            - 内容：True 表示可以发布，False 表示需要修正后重新审核
            - 用途：控制工作流的分支逻辑（通过 → 分发，未通过 → 修正 → 重新审核）

        iteration (int): 当前审核循环次数
            - 内容：从 0 开始递增，最多允许 3 次循环（0, 1, 2）
            - 用途：防止无限循环，超过 3 次后强制进入"仅发布高质量条目"模式
            - 示例流程：
              - iteration=0：首次审核，所有条目都可修正
              - iteration=1：第二次审核，部分条目可能已排除
              - iteration=2：最后一次审核，仅发布 score >= 7 的条目
              - iteration>2：退出循环，发布现有合格条目

        cost_tracker (dict): Token 用量和成本追踪
            - 内容：AI API 调用的计费数据汇总
            - 格式示例：
              {
                "total_input_tokens": 50000,
                "total_output_tokens": 25000,
                "total_api_calls": 42,
                "model_used": "deepseek-chat",
                "estimated_cost_usd": 0.75,
                "calls_by_node": {
                  "analyzer": {"input": 40000, "output": 20000, "calls": 30},
                  "reviewer": {"input": 10000, "output": 5000, "calls": 12}
                }
              }
            - 用途：监控成本，避免异常调用

    Notes:
        - 所有字段使用结构化数据（dict/list），避免存储原始文本内容
        - 文件路径字段（如 `analysis_file`）用于后续读取完整数据
        - 状态演化流程：
          sources → analyses → articles → review → (修正循环) → 分发
        - 审核循环最多 3 次，超出后按现有规则发布（过滤 score < 5 的条目）
    """

    sources: list[dict]
    analyses: list[dict]
    articles: list[dict]
    review_feedback: str
    review_passed: bool
    iteration: int
    cost_tracker: dict
