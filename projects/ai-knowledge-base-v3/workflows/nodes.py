"""工作流共享工具模块：时间、JSON 解析、成本追踪、目录管理等通用函数。

各节点文件从此模块导入共享工具，节点函数本身已拆分至独立文件：
  collector.py  — 数据采集
  analyzer.py   — LLM 单条分析
  organizer.py  — 整理入库
  reviewer.py   — 5 维加权审核
  reviser.py    — 读反馈定向修改
  planner.py    — 动态规划策略
  human_flag.py — 人工介入标记
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

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

from model_client import PRICING, Usage  # noqa: E402

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

CST = timezone(timedelta(hours=8))
RAW_DIR = _PROJECT_ROOT / "knowledge" / "raw"
ARTICLES_DIR = _PROJECT_ROOT / "knowledge" / "articles"
INDEX_FILE = ARTICLES_DIR / "index.json"

AI_KEYWORDS_RE = re.compile(
    r"\b(ai|llm|agent|gpt|openai|deepseek|qwen|claude|transformer|"
    r"rag|langchain|llama|mistral|gemini|neural|diffusion|"
    r"nlp|machine.learning|deep.learning|prompt)\b",
    re.IGNORECASE,
)

VALID_CATEGORIES = frozenset(
    {"model_release", "agent_framework", "tool", "paper", "opinion"}
)

# 需求：过滤低分条目 <0.6；relevance_score 为 1-10 整数制，0.6×10 = 6
RELEVANCE_MIN = 6

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return current time in ISO 8601 with CST offset."""
    return datetime.now(CST).isoformat()


def _today_str() -> str:
    """Return today's date as YYYYMMDD in CST."""
    return datetime.now(CST).strftime("%Y%m%d")


def _slugify(text: str, max_len: int = 60) -> str:
    """Generate a URL/filesystem-safe slug from text.

    Args:
        text: Input text (title or repo name).
        max_len: Maximum slug length.

    Returns:
        Lowercase hyphenated ASCII slug.
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_len].strip("-")


def _parse_json_response(raw: str) -> dict[str, Any]:
    """Extract the first JSON object or array from a raw LLM response.

    Handles ```json … ``` fences and leading/trailing noise.  Searches
    anywhere in the string, not anchored to start/end.

    Args:
        raw: Raw LLM response string.

    Returns:
        Parsed JSON dict or list.

    Raises:
        json.JSONDecodeError: If no valid JSON is found.
    """
    text = raw.strip()
    # Try fenced code block (```json ... ``` or ``` ... ```)
    m = re.search(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Try to find a JSON object or array anywhere in the text
    m = re.search(r"[\[\{].*[\]\}]", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    # Log a snippet of the raw response for debugging
    preview = raw[:200] if raw else "(empty)"
    raise json.JSONDecodeError(
        f"No JSON object/array found in LLM response (preview: {preview})",
        raw, 0,
    )


def accumulate_usage(tracker: dict, usage: Usage) -> None:
    """Accumulate token stats from one LLM call into a cost-tracker dict.

    Uses .get() defaults so the tracker does not need to be pre-populated.

    Args:
        tracker: Mutable cost-tracker dict (modified in-place).
        usage: Usage object returned by chat_with_retry().
    """
    tracker["total_input_tokens"] = tracker.get("total_input_tokens", 0) + usage.prompt_tokens
    tracker["total_output_tokens"] = tracker.get("total_output_tokens", 0) + usage.completion_tokens
    tracker["total_api_calls"] = tracker.get("total_api_calls", 0) + 1


def _compute_cost(tracker: dict, provider: str = "deepseek") -> float:
    """Compute estimated USD cost from accumulated token counts.

    Args:
        tracker: Cost-tracker dict with total_input_tokens / total_output_tokens.
        provider: Provider key for PRICING lookup (deepseek / qwen / openai).

    Returns:
        Estimated cost in USD, rounded to 6 decimal places.
    """
    pricing = PRICING.get(provider, PRICING["deepseek"])
    cost = (
        tracker.get("total_input_tokens", 0) / 1_000_000 * pricing["input"]
        + tracker.get("total_output_tokens", 0) / 1_000_000 * pricing["output"]
    )
    return round(cost, 6)


def _ensure_dirs() -> None:
    """Create required output directories if they don't exist."""
    for d in (RAW_DIR, ARTICLES_DIR):
        d.mkdir(parents=True, exist_ok=True)
