"""Analyzer 节点：调用 LLM 逐条分析原始采集数据，生成中文摘要、标签、评分。

输出写入 knowledge/articles/YYYYMMDD-github-analysis.json，
返回 state["analyses"] 摘要和 state["articles"] 分析结果列表。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from state import KBState
from nodes import (
    _now_iso,
    _today_str,
    _parse_json_response,
    accumulate_usage,
    _compute_cost,
    ARTICLES_DIR,
    VALID_CATEGORIES,
)

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

ANALYSIS_SYSTEM_PROMPT = (
    "你是一个AI技术分析专家。请严格按指定JSON格式输出分析结果，"
    "不要输出任何其他文字、代码块标记或解释。"
)


# ---------------------------------------------------------------------------
# 分析节点
# ---------------------------------------------------------------------------


def analyze_node(state: KBState) -> dict:
    """Analyze raw collected items using LLM.

    Generates Chinese title, summary, tags, category, and relevance score for
    each item, then saves a batch analysis file to knowledge/articles/.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update: {"analyses": [...], "articles": [...], "cost_tracker": {...}}.
    """
    logger.info("[Analyzer] Starting AI analysis of collected items")

    if not state.get("sources"):
        logger.warning("[Analyzer] No sources to analyze")
        return {"analyses": [], "articles": []}

    try:
        client = create_client()
    except ValueError as e:
        logger.error("[Analyzer] Failed to create LLM client: %s", e)
        return {"analyses": [], "articles": []}

    cost_tracker: dict = state.get("cost_tracker") or {}
    analyses: list[dict] = []
    analysis_results: list[dict] = []

    for source_info in state["sources"]:
        source_file = Path(source_info["file_path"])
        if not source_file.exists():
            logger.warning("[Analyzer] Source file not found: %s", source_file)
            continue

        with open(source_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        items = raw_data.get("items", [])
        success_count = 0
        failed_items: list[dict] = []

        for idx, item in enumerate(items):
            logger.info(
                "[Analyzer] Analyzing item %d/%d: %s", idx + 1, len(items), item["name"]
            )

            prompt = f"""分析以下GitHub项目并输出一个JSON对象：

名称：{item['name']}
描述：{item['description']}
语言：{item['language']}
标签：{', '.join(item['topics'])}
星数：{item['stars']}

输出格式：
{{
  "title": "中文标题（30字以内，含项目名，吸引人但不浮夸）",
  "summary": "中文摘要，1-3句，涵盖核心价值和创新点（50-150字）",
  "tags": ["标签1", "标签2", "标签3", "标签4", "标签5"],
  "category": "model_release/agent_framework/tool/paper/opinion",
  "relevance_score": 1,
  "key_points": ["要点1", "要点2", "要点3"],
  "sentiment": "positive/neutral/negative"
}}

评分参考：
- 10: 里程碑式（GPT-5发布等）
- 8-9: 非常重要（主流框架大更新）
- 6-7: 重要（有趣的新项目/工具）
- 4-5: 一般相关
- 1-3: 边缘相关

只输出JSON对象，不要markdown代码块。"""

            try:
                messages = [
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
                response = client.chat_with_retry(messages, max_tokens=1000)
                parsed = _parse_json_response(response.content)

                parsed["id"] = f"github-{_today_str()}-{len(analysis_results) + 1:03d}"
                parsed["title"] = str(parsed.get("title", item["name"]))[:100]
                parsed["summary"] = str(parsed.get("summary", ""))[:500]
                parsed["tags"] = parsed.get("tags", [])[:5]
                parsed["category"] = parsed.get("category", "tool")
                if parsed["category"] not in VALID_CATEGORIES:
                    parsed["category"] = "tool"
                parsed["relevance_score"] = max(1, min(10, int(parsed.get("relevance_score", 5))))
                parsed["key_points"] = parsed.get("key_points", [])[:5]
                parsed["sentiment"] = parsed.get("sentiment", "neutral")
                parsed["source"] = "github_trending"
                parsed["source_url"] = item["url"]
                parsed["status"] = "draft"
                parsed["collected_at"] = _now_iso()
                parsed["published_at"] = None

                analysis_results.append(parsed)
                success_count += 1
                accumulate_usage(cost_tracker, response.usage)
                logger.info(
                    "[Analyzer] OK: %s (score=%d)", parsed["title"], parsed["relevance_score"]
                )

            except Exception as e:
                logger.error("[Analyzer] Failed to analyze %s: %s", item["name"], e)
                failed_items.append({"title": item["name"], "error": str(e)})

        analysis_file = ARTICLES_DIR / f"{_today_str()}-github-analysis.json"
        with open(analysis_file, "w", encoding="utf-8") as f:
            json.dump(analysis_results, f, ensure_ascii=False, indent=2)
        logger.info("[Analyzer] Analysis saved to %s", analysis_file)

        analyses.append({
            "analysis_id": f"github-{_today_str()}",
            "source": raw_data["source"],
            "analyzed_count": len(items),
            "success_count": success_count,
            "failed_items": failed_items,
            "analysis_file": str(analysis_file),
            "analyzed_at": _now_iso(),
        })

    cost_tracker["estimated_cost_usd"] = _compute_cost(cost_tracker, client.provider)

    return {
        "analyses": analyses,
        "articles": analysis_results,
        "cost_tracker": cost_tracker,
    }
