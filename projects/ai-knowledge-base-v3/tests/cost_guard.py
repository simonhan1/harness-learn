#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""多 Agent 预算守卫模块。

提供 LLM 调用成本追踪、预算预警和超限保护功能。
"""

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """预算超限异常。"""

    pass


@dataclass
class CostRecord:
    """单次 LLM 调用成本记录。

    Attributes:
        timestamp: 调用时间（ISO 8601 格式）。
        node_name: 调用节点名称。
        prompt_tokens: 输入 token 数。
        completion_tokens: 输出 token 数。
        cost_yuan: 本次调用成本（元）。
        model: 模型名称。
    """

    timestamp: str
    node_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    model: str = ""


class CostGuard:
    """多 Agent 预算守卫，提供三重保护机制。

    1. 记录每次 LLM 调用的 token 用量与成本。
    2. 检查预算状态，接近预算时告警，超出时抛异常。
    3. 生成和保存按节点分组的成本报告。

    Attributes:
        budget_yuan: 总预算（元）。
        alert_threshold: 预警阈值比例。
        input_price_per_million: 输入 token 单价（元/百万 token）。
        output_price_per_million: 输出 token 单价（元/百万 token）。
    """

    def __init__(
        self,
        budget_yuan: float = 1.0,
        alert_threshold: float = 0.8,
        input_price_per_million: float = 1.0,
        output_price_per_million: float = 2.0,
    ):
        """初始化预算守卫。

        Args:
            budget_yuan: 总预算（元），默认 1.0。
            alert_threshold: 预警阈值比例，默认 0.8。
            input_price_per_million: 输入 token 单价，默认 1.0 元/百万 token。
            output_price_per_million: 输出 token 单价，默认 2.0 元/百万 token。
        """
        self.budget_yuan = budget_yuan
        self.alert_threshold = alert_threshold
        self.input_price_per_million = input_price_per_million
        self.output_price_per_million = output_price_per_million
        self._records: list[CostRecord] = []

    def record(self, node_name: str, usage: dict, model: str = "") -> CostRecord:
        """记录一次 LLM 调用的 token 用量。

        Args:
            node_name: 调用节点名称。
            usage: Token 用量，格式 {"prompt_tokens": int, "completion_tokens": int}。
            model: 模型名称，可选。

        Returns:
            新创建的 CostRecord 实例。
        """
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))

        cost = (
            prompt_tokens * self.input_price_per_million / 1_000_000
            + completion_tokens * self.output_price_per_million / 1_000_000
        )

        record = CostRecord(
            timestamp=datetime.now().isoformat(),
            node_name=node_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_yuan=round(cost, 6),
            model=model,
        )
        self._records.append(record)
        logger.info(
            "CostGuard record: node=%s, prompt=%d, completion=%d, cost=%.6f",
            node_name,
            prompt_tokens,
            completion_tokens,
            record.cost_yuan,
        )
        return record

    @property
    def total_prompt_tokens(self) -> int:
        """所有记录的输入 token 总数。"""
        return sum(r.prompt_tokens for r in self._records)

    @property
    def total_completion_tokens(self) -> int:
        """所有记录的输出 token 总数。"""
        return sum(r.completion_tokens for r in self._records)

    @property
    def total_cost_yuan(self) -> float:
        """所有记录的总成本（元）。"""
        return round(sum(r.cost_yuan for r in self._records), 6)

    def check(self) -> dict:
        """检查预算状态。

        Returns:
            预算状态字典，包含:
                - status: "ok" 或 "warning"
                - total_cost: 当前总成本
                - budget: 预算总额
                - usage_ratio: 预算使用比例
                - message: 状态描述

        Raises:
            BudgetExceededError: 当总成本超出预算时抛出。
        """
        total = self.total_cost_yuan
        usage_ratio = total / self.budget_yuan if self.budget_yuan > 0 else float("inf")

        if usage_ratio >= 1.0:
            raise BudgetExceededError(
                f"预算已超限！已花费 ¥{total:.4f} / ¥{self.budget_yuan:.4f} "
                f"({usage_ratio:.1%})"
            )

        if usage_ratio >= self.alert_threshold:
            return {
                "status": "warning",
                "total_cost": total,
                "budget": self.budget_yuan,
                "usage_ratio": round(usage_ratio, 4),
                "message": f"预算预警：已使用 {usage_ratio:.1%}，接近上限",
            }

        return {
            "status": "ok",
            "total_cost": total,
            "budget": self.budget_yuan,
            "usage_ratio": round(usage_ratio, 4),
            "message": "预算正常",
        }

    def get_report(self) -> dict:
        """生成按节点分组的成本报告。

        Returns:
            成本报告字典，包含汇总信息和各节点明细。
        """
        node_stats: dict[str, dict] = {}
        for r in self._records:
            if r.node_name not in node_stats:
                node_stats[r.node_name] = {
                    "call_count": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_yuan": 0.0,
                    "models": set(),
                }
            stats = node_stats[r.node_name]
            stats["call_count"] += 1
            stats["prompt_tokens"] += r.prompt_tokens
            stats["completion_tokens"] += r.completion_tokens
            stats["cost_yuan"] += r.cost_yuan
            if r.model:
                stats["models"].add(r.model)

        for name in node_stats:
            node_stats[name]["models"] = sorted(node_stats[name]["models"])
            node_stats[name]["cost_yuan"] = round(node_stats[name]["cost_yuan"], 6)

        return {
            "total_cost_yuan": self.total_cost_yuan,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_calls": len(self._records),
            "budget_yuan": self.budget_yuan,
            "alert_threshold": self.alert_threshold,
            "nodes": node_stats,
        }

    def save_report(self, path: Optional[str] = None) -> str:
        """保存成本报告到 JSON 文件。

        Args:
            path: 保存路径，为 None 时自动生成默认文件名。

        Returns:
            实际保存的文件路径。
        """
        if path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"cost_report_{ts}.json"

        report = self.get_report()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("成本报告已保存到 %s", path)
        return path


# ---------------------------------------------------------------------------
# 自测代码
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    # 防止 Windows GBK 编码报错
    sys.stdout.reconfigure(encoding="utf-8")

    PASS = "[PASS]"
    FAIL = "[FAIL]"

    print("=" * 70)
    print("CostGuard 自测套件")
    print("=" * 70)

    all_passed = True
    failed_tests = []

    # --- 测试 1: 成本追踪正确 ---
    print("\n[TEST 1] 成本追踪")
    print("-" * 70)
    try:
        cg = CostGuard(budget_yuan=1.0, input_price_per_million=1.0, output_price_per_million=2.0)
        cg.record("analyzer", {"prompt_tokens": 500_000, "completion_tokens": 100_000}, model="gpt-4o")
        cg.record("collector", {"prompt_tokens": 200_000, "completion_tokens": 50_000})

        expected_cost = (
            500_000 * 1.0 / 1_000_000 + 100_000 * 2.0 / 1_000_000
            + 200_000 * 1.0 / 1_000_000 + 50_000 * 2.0 / 1_000_000
        )
        assert cg.total_prompt_tokens == 700_000, (
            f"total_prompt_tokens 应为 700000，实际 {cg.total_prompt_tokens}"
        )
        assert cg.total_cost_yuan == round(expected_cost, 6), (
            f"total_cost_yuan 应为 {round(expected_cost, 6)}，实际 {cg.total_cost_yuan}"
        )
        print(f"  prompt_tokens={cg.total_prompt_tokens} {PASS}")
        print(f"  completion_tokens={cg.total_completion_tokens} {PASS}")
        print(f"  total_cost_yuan={cg.total_cost_yuan} {PASS}")
        print(f"{PASS} 成本追踪测试通过")
    except AssertionError as e:
        print(f"{FAIL} {e}")
        all_passed = False
        failed_tests.append("TEST 1")

    # --- 测试 2: 预算超限检测 ---
    print("\n[TEST 2] 预算超限检测")
    print("-" * 70)
    try:
        cg2 = CostGuard(budget_yuan=0.001, input_price_per_million=1.0, output_price_per_million=2.0)
        cg2.record("test", {"prompt_tokens": 2_000, "completion_tokens": 0})

        try:
            cg2.check()
            print(f"{FAIL} 应抛出 BudgetExceededError 但未抛出")
            all_passed = False
            failed_tests.append("TEST 2")
        except BudgetExceededError as e:
            print(f"  捕获 BudgetExceededError {PASS}")
            print(f"  消息: {e}")
            print(f"{PASS} 预算超限检测测试通过")
    except AssertionError as e:
        print(f"{FAIL} {e}")
        all_passed = False
        failed_tests.append("TEST 2")

    # --- 测试 3: 预警阈值触发 ---
    print("\n[TEST 3] 预警阈值触发")
    print("-" * 70)
    try:
        cg3 = CostGuard(budget_yuan=1.0, alert_threshold=0.5, input_price_per_million=1.0)
        cg3.record("analyzer", {"prompt_tokens": 600_000, "completion_tokens": 0})

        result = cg3.check()
        assert result["status"] == "warning", f"status 应为 'warning'，实际 '{result['status']}'"
        assert result["usage_ratio"] >= 0.5, f"usage_ratio 应 >= 0.5"
        print(f"  status={result['status']} {PASS}")
        print(f"  usage_ratio={result['usage_ratio']} {PASS}")
        print(f"  message={result['message']} {PASS}")
        print(f"{PASS} 预警阈值测试通过")
    except AssertionError as e:
        print(f"{FAIL} {e}")
        all_passed = False
        failed_tests.append("TEST 3")

    # --- 测试 4: 正常状态 ---
    print("\n[TEST 4] 正常状态")
    print("-" * 70)
    try:
        cg4 = CostGuard(budget_yuan=1.0, alert_threshold=0.8)
        cg4.record("collector", {"prompt_tokens": 100_000, "completion_tokens": 0})

        result = cg4.check()
        assert result["status"] == "ok", f"status 应为 'ok'，实际 '{result['status']}'"
        print(f"  status={result['status']} {PASS}")
        print(f"{PASS} 正常状态测试通过")
    except AssertionError as e:
        print(f"{FAIL} {e}")
        all_passed = False
        failed_tests.append("TEST 4")

    # --- 测试 5: get_report / save_report ---
    print("\n[TEST 5] get_report / save_report")
    print("-" * 70)
    try:
        cg5 = CostGuard(budget_yuan=1.0, input_price_per_million=1.0, output_price_per_million=2.0)
        cg5.record("analyzer", {"prompt_tokens": 500_000, "completion_tokens": 100_000}, model="gpt-4o")
        cg5.record("collector", {"prompt_tokens": 200_000, "completion_tokens": 50_000})

        report = cg5.get_report()
        assert "nodes" in report, "报告缺少 'nodes'"
        assert "analyzer" in report["nodes"], "报告缺少 'analyzer' 节点"
        assert report["nodes"]["analyzer"]["call_count"] == 1
        assert report["total_calls"] == 2
        print(f"  节点数: {len(report['nodes'])} {PASS}")
        print(f"  总调用: {report['total_calls']} {PASS}")

        saved = cg5.save_report("test_cost_report.json")
        with open(saved, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["total_cost_yuan"] == cg5.total_cost_yuan
        print(f"  报告已保存到 {saved} {PASS}")
        print(f"{PASS} 报告功能测试通过")
    except AssertionError as e:
        print(f"{FAIL} {e}")
        all_passed = False
        failed_tests.append("TEST 5")
    finally:
        from pathlib import Path
        Path("test_cost_report.json").unlink(missing_ok=True)

    # --- 汇总 ---
    print("\n" + "=" * 70)
    if all_passed:
        print("所有测试通过！")
    else:
        print(f"存在 {len(failed_tests)} 个失败测试: {', '.join(failed_tests)}")
    print("=" * 70)
