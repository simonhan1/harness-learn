#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AI 知识库评估测试。

包含本地验证测试和 LLM-as-Judge 测试，使用 pytest 框架。
"""

from __future__ import annotations

import json
import logging
import warnings

from dotenv import load_dotenv

load_dotenv()

# 屏蔽 PytestUnknownMarkWarning（自定义 slow 标记）
warnings.filterwarnings(
    "ignore",
    message=r".*Unknown pytest\.mark.*",
)

import pytest  # noqa: E402

from pipeline.model_client import create_client  # noqa: E402

logger = logging.getLogger(__name__)

# ============================================================================
# EVAL_CASES — 评估用例
# ============================================================================

EVAL_CASES: list[dict] = [
    {
        "name": "positive_tech_article",
        "description": "正面案例：技术文章输入，预期有摘要、有关键词",
        "input": (
            "OpenAI 发布了 GPT-5 模型，支持多模态推理与 Agent 原生调用，"
            "推理成本降低 50%，上下文窗口扩展至 1M tokens。"
        ),
        "expected": lambda result: (
            len(result.get("summary", "")) >= 10
            and len(result.get("tags", [])) >= 1
            and result.get("relevance_score", 0) >= 6
        ),
    },
    {
        "name": "negative_irrelevant",
        "description": "负面案例：无关内容输入，预期被标记为低相关",
        "input": (
            "今天天气晴朗，最高气温 25 度，适合出门野餐。"
            "小明在公园里放风筝玩得很开心。"
        ),
        "expected": lambda result: (
            result.get("relevance_score", 10) <= 5
        ),
    },
    {
        "name": "boundary_short_input",
        "description": "边界案例：极短输入 'AI'，预期不崩溃且返回有效结构",
        "input": "AI",
        "expected": lambda result: (
            result is not None
            and isinstance(result, dict)
            and "summary" in result
            and "tags" in result
            and isinstance(result["tags"], list)
        ),
    },
    {
        "name": "mixed_cn_en_tech",
        "description": "混合中英文技术内容，预期正确识别技术关键词",
        "input": (
            "LangChain v0.3 新增 LCEL (LangChain Expression Language) 语法，"
            "支持 streaming 和 async 调用，Agent 开发效率大幅提升。"
        ),
        "expected": lambda result: (
            len(result.get("summary", "")) >= 10
            and len(result.get("tags", [])) >= 1
            and result.get("relevance_score", 0) >= 5
        ),
    },
    {
        "name": "long_technical_with_numbers",
        "description": "长文本含技术参数，预期摘要不超过输入长度",
        "input": (
            "Meta 开源 Llama 4 系列模型，包含 8B、70B、400B 三个规模。"
            "在 MMLU 基准上达到 89.7 分，HumanEval 达到 82.4 分。"
            "支持 128K 上下文，采用 MoE 架构，训练数据超过 30T tokens。"
        ),
        "expected": lambda result: (
            len(result.get("summary", "")) <= len(
                "Meta 开源 Llama 4 系列模型，包含 8B、70B、400B 三个规模。"
                "在 MMLU 基准上达到 89.7 分，HumanEval 达到 82.4 分。"
                "支持 128K 上下文，采用 MoE 架构，训练数据超过 30T tokens。"
            )
            and result.get("relevance_score", 0) >= 5
        ),
    },
]

# ============================================================================
# 模拟分析器 — 不调用 LLM 的本地分析函数
# ============================================================================

_AI_KEYWORDS = frozenset({
    "AI", "LLM", "GPT", "Agent", "模型", "推理", "训练", "开源",
    "OpenAI", "LangChain", "Llama", "transformer", "RAG", "prompt",
    "fine-tune", "多模态", "token", "上下文", "MoE", "embedding",
    "深度学习", "机器学习", "神经网络", "generative", "chatbot",
    "向量", "知识库", "大模型", "语义", "NLP", "NLG", "CUDA",
})


def _mock_analyze(text: str) -> dict:
    """模拟分析：根据输入文本生成分析结果。

    根据关键词命中数估算 relevance_score，不调用 LLM。

    Args:
        text: 待分析的文本。

    Returns:
        模拟的分析结果字典。
    """
    hits = sum(1 for kw in _AI_KEYWORDS if kw.lower() in text.lower())
    score = max(1, min(10, hits * 2 + 1))

    tags: list[str] = sorted(
        {kw for kw in _AI_KEYWORDS if kw.lower() in text.lower()}
    )
    summary = text if len(text) <= 150 else text[:147] + "..."

    return {
        "title": text[:30] if len(text) >= 30 else text,
        "summary": summary,
        "tags": tags,
        "category": "tool",
        "relevance_score": score,
        "key_points": [],
        "sentiment": "neutral",
    }


# ============================================================================
# 测试 — 本地验证
# ============================================================================


class TestEvalCasesStructure:
    """验证 EVAL_CASES 数据结构。"""

    def test_eval_cases_is_non_empty_list(self) -> None:
        """EVAL_CASES 应为非空列表。"""
        assert isinstance(EVAL_CASES, list), "EVAL_CASES 应为 list"
        assert len(EVAL_CASES) >= 3, "至少需要 3 个评估用例"

    def test_each_case_has_required_keys(self) -> None:
        """每个用例应包含 name, input, expected。"""
        required = {"name", "input", "expected"}
        for case in EVAL_CASES:
            missing = required - set(case.keys())
            assert not missing, f"用例 {case.get('name', '?')} 缺少字段: {missing}"

    def test_input_is_non_empty_string(self) -> None:
        """每个用例的 input 应为非空字符串。"""
        for case in EVAL_CASES:
            inp = case["input"]
            assert isinstance(inp, str), (
                f"用例 {case['name']} 的 input 应为 str，实际 {type(inp).__name__}"
            )
            assert len(inp.strip()) > 0, f"用例 {case['name']} 的 input 为空"

    def test_expected_is_callable(self) -> None:
        """每个用例的 expected 应为可调用对象。"""
        for case in EVAL_CASES:
            assert callable(case["expected"]), (
                f"用例 {case['name']} 的 expected 不可调用"
            )

    def test_expected_returns_bool(self) -> None:
        """每个 expected 函数对 mock 结果应返回 bool。"""
        for case in EVAL_CASES:
            result = _mock_analyze(case["input"])
            outcome = case["expected"](result)
            assert isinstance(outcome, bool), (
                f"用例 {case['name']} 的 expected 应返回 bool，"
                f"实际返回 {type(outcome).__name__}"
            )


class TestMockAnalysis:
    """使用模拟分析器验证 EVAL_CASES 的预期条件。"""

    @pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c["name"])
    def test_case_expected_condition(self, case: dict) -> None:
        """模拟分析结果应满足用例的 expected 条件。"""
        result = _mock_analyze(case["input"])
        assert case["expected"](result), (
            f"用例 [{case['name']}] 未通过: {case.get('description', '')}"
        )

    def test_negative_case_low_score(self) -> None:
        """负面用例的 relevance_score 应 <= 5。"""
        for case in EVAL_CASES:
            if "negative" in case["name"]:
                result = _mock_analyze(case["input"])
                assert result["relevance_score"] <= 5, (
                    f"负面用例 {case['name']} 的 relevance_score 应为 <= 5"
                )

    def test_positive_case_has_tags(self) -> None:
        """正面用例应至少包含 1 个标签。"""
        for case in EVAL_CASES:
            if "positive" in case["name"]:
                result = _mock_analyze(case["input"])
                assert len(result["tags"]) >= 1, (
                    f"正面用例 {case['name']} 应有 ≥ 1 个标签"
                )


# ============================================================================
# 测试 — LLM-as-Judge（标记为 slow）
# ============================================================================


_JUDGE_ANALYSIS_SAMPLE: dict = {
    "title": "OpenAI 发布 GPT-5：多模态推理与 Agent 原生支持",
    "summary": (
        "OpenAI 正式发布 GPT-5 模型，在推理能力、多模态理解、Agent 原生调用"
        "三个维度均有重大突破。推理成本较 GPT-4 降低 50%，上下文窗口扩展至 "
        "1M tokens，标志着大模型进入实用化新阶段。"
    ),
    "tags": ["OpenAI", "GPT-5", "LLM", "多模态", "Agent"],
    "category": "model_release",
    "relevance_score": 9,
    "key_points": [
        "多模态推理能力大幅提升",
        "推理成本降低 50%",
        "支持 Agent 原生调用",
        "上下文窗口 1M tokens",
    ],
    "sentiment": "positive",
    "source": "github_trending",
    "source_url": "https://github.com/openai/gpt-5",
    "status": "draft",
}

_JUDGE_SYSTEM_PROMPT = (
    "你是一个 AI 知识库质量控制专家。请对以下分析结果进行评分（1-10 分），"
    "考察维度：摘要质量、标签准确性、分类合理性、整体价值。\n"
    "只输出一个 JSON 对象: {\"score\": <1-10>, \"reason\": \"<简短理由>\"}\n"
    "不要输出任何其他内容。"
)


def _call_judge(analysis: dict) -> dict:
    """调用 LLM 对分析结果打分。

    Args:
        analysis: 分析结果字典。

    Returns:
        LLM 返回的评分 JSON。

    Raises:
        RuntimeError: LLM 调用失败或返回无法解析时。
    """
    client = create_client()
    analysis_json = json.dumps(analysis, ensure_ascii=False, indent=2)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": analysis_json},
    ]
    response = client.chat_with_retry(messages, temperature=0.3, max_tokens=256)

    # 尝试解析 JSON 响应
    content = response.content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()
    return json.loads(content)


@pytest.mark.slow
class TestLLMAsJudge:
    """LLM-as-Judge：让 LLM 对分析结果打分。"""

    def test_judge_score_at_least_5(self) -> None:
        """LLM 对高质量分析结果的评分应 >= 5。"""
        try:
            verdict = _call_judge(_JUDGE_ANALYSIS_SAMPLE)
        except Exception as e:
            pytest.skip(f"LLM 调用失败，跳过 LLM-as-Judge 测试: {e}")

        score = int(verdict.get("score", 0))
        reason = verdict.get("reason", "")

        logger.info("LLM Judge score: %d, reason: %s", score, reason)
        assert score >= 5, (
            f"LLM Judge 评分过低: {score}/10, 理由: {reason}"
        )
        assert 1 <= score <= 10, f"评分超出范围: {score}"

    def test_judge_response_has_reason(self) -> None:
        """LLM Judge 返回结果应包含评分理由。"""
        try:
            verdict = _call_judge(_JUDGE_ANALYSIS_SAMPLE)
        except Exception as e:
            pytest.skip(f"LLM 调用失败，跳过 LLM-as-Judge 测试: {e}")

        assert "score" in verdict, "缺少 score 字段"
        assert "reason" in verdict, "缺少 reason 字段"
        assert len(verdict["reason"]) >= 5, "reason 过短"

    def test_judge_low_quality_analysis(self) -> None:
        """LLM 对低质量分析结果应给较低分。"""
        low_quality: dict = {
            "title": "something",
            "summary": "ok",
            "tags": [],
            "category": "tool",
            "relevance_score": 1,
            "key_points": [],
            "sentiment": "neutral",
        }
        try:
            verdict = _call_judge(low_quality)
        except Exception as e:
            pytest.skip(f"LLM 调用失败，跳过 LLM-as-Judge 测试: {e}")

        score = int(verdict.get("score", 10))
        logger.info("LLM Judge low-quality score: %d", score)
        # 低质量分析不应得满分
        assert score <= 9, f"低质量分析不应得满分: {score}/10"
