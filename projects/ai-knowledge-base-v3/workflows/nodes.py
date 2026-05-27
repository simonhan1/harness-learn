"""LangGraph 工作流的 5 个节点函数定义。

采集 → 分析 → 整理 → 审核 → 保存

每个节点是纯函数：接收 KBState，返回 dict（部分状态更新）。
LLM 调用统一通过 pipeline/model_client 的 create_client() 完成。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from state import KBState

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

from model_client import PRICING, Usage, create_client  # noqa: E402

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

CST = timezone(timedelta(hours=8))
RAW_DIR = _PROJECT_ROOT / "knowledge" / "raw"
ARTICLES_DIR = _PROJECT_ROOT / "knowledge" / "articles"
INDEX_FILE = ARTICLES_DIR / "index.json"

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_TIMEOUT = 30.0
GITHUB_PER_PAGE = 30

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

ANALYSIS_SYSTEM_PROMPT = (
    "你是一个AI技术分析专家。请严格按指定JSON格式输出分析结果，"
    "不要输出任何其他文字、代码块标记或解释。"
)
REVIEW_SYSTEM_PROMPT = (
    "你是一个AI知识库内容审核专家。请严格按JSON格式输出审核结果，"
    "包含通过/失败决策、总体评分和具体反馈。不要输出任何其他文字。"
)
CORRECTION_SYSTEM_PROMPT = "你是一个AI内容编辑，根据审核反馈精准修正知识条目。"

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
    """Extract the first JSON object from a raw LLM response.

    Handles ```json … ``` fences and leading/trailing noise.

    Args:
        raw: Raw LLM response string.

    Returns:
        Parsed JSON dict.

    Raises:
        json.JSONDecodeError: If no valid JSON object is found.
    """
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise json.JSONDecodeError("No JSON object found in LLM response", raw, 0)


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


# ---------------------------------------------------------------------------
# 节点 1: COLLECT_NODE — 采集 GitHub Trending 数据
# ---------------------------------------------------------------------------


def collect_node(state: KBState) -> dict:
    """Collect AI-related trending repos from GitHub Search API.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update: {"sources": [...]}.
    """
    logger.info("[CollectNode] Starting GitHub trending data collection")

    _ensure_dirs()

    params: dict[str, str | int] = {
        "q": "ai OR llm OR agent OR gpt OR openai topics:>=1",
        "sort": "stars",
        "order": "desc",
        "per_page": GITHUB_PER_PAGE,
    }
    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    if token := os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    collected_items: list[dict[str, Any]] = []

    try:
        logger.info("[CollectNode] Fetching GitHub Search API: q=%s", params["q"])
        resp = httpx.get(
            GITHUB_SEARCH_URL,
            params=params,
            headers=headers,
            timeout=GITHUB_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", [])[:GITHUB_PER_PAGE]:
            desc = item.get("description") or ""
            topics = item.get("topics") or []
            if AI_KEYWORDS_RE.search(f"{desc} {' '.join(topics)}"):
                collected_items.append({
                    "name": item["full_name"],
                    "url": item["html_url"],
                    "description": desc,
                    "stars": item["stargazers_count"],
                    "language": item.get("language") or "",
                    "topics": topics,
                })

        logger.info("[CollectNode] Collected %d AI-related items", len(collected_items))

        ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
        raw_file = RAW_DIR / f"github_trending_{ts}.json"
        with open(raw_file, "w", encoding="utf-8") as f:
            json.dump(
                {"source": "github_trending", "collected_at": _now_iso(), "items": collected_items},
                f, ensure_ascii=False, indent=2,
            )
        logger.info("[CollectNode] Raw data saved to %s", raw_file)

        return {
            "sources": [
                {
                    "source": "github_trending",
                    "collected_at": _now_iso(),
                    "count": len(collected_items),
                    "file_path": str(raw_file),
                }
            ]
        }

    except Exception as e:
        logger.error("[CollectNode] Collection failed: %s", e, exc_info=True)
        return {"sources": []}


# ---------------------------------------------------------------------------
# 节点 2: ANALYZE_NODE — LLM 分析每条数据
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
    logger.info("[AnalyzeNode] Starting AI analysis of collected items")

    if not state.get("sources"):
        logger.warning("[AnalyzeNode] No sources to analyze")
        return {"analyses": [], "articles": []}

    try:
        client = create_client()
    except ValueError as e:
        logger.error("[AnalyzeNode] Failed to create LLM client: %s", e)
        return {"analyses": [], "articles": []}

    cost_tracker: dict = state.get("cost_tracker") or {}
    analyses: list[dict] = []
    analysis_results: list[dict] = []

    for source_info in state["sources"]:
        source_file = Path(source_info["file_path"])
        if not source_file.exists():
            logger.warning("[AnalyzeNode] Source file not found: %s", source_file)
            continue

        with open(source_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        items = raw_data.get("items", [])
        success_count = 0
        failed_items: list[dict] = []

        for idx, item in enumerate(items):
            logger.info(
                "[AnalyzeNode] Analyzing item %d/%d: %s", idx + 1, len(items), item["name"]
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
                    "[AnalyzeNode] OK: %s (score=%d)", parsed["title"], parsed["relevance_score"]
                )

            except Exception as e:
                logger.error("[AnalyzeNode] Failed to analyze %s: %s", item["name"], e)
                failed_items.append({"title": item["name"], "error": str(e)})

        analysis_file = ARTICLES_DIR / f"{_today_str()}-github-analysis.json"
        with open(analysis_file, "w", encoding="utf-8") as f:
            json.dump(analysis_results, f, ensure_ascii=False, indent=2)
        logger.info("[AnalyzeNode] Analysis saved to %s", analysis_file)

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


# ---------------------------------------------------------------------------
# 节点 3: ORGANIZE_NODE — 去重、过滤、迭代修正
# ---------------------------------------------------------------------------


def organize_node(state: KBState) -> dict:
    """Organize articles: dedup by URL, filter low-relevance, apply LLM corrections.

    When iteration > 0 and review_feedback is non-empty, each article is passed
    to the LLM for targeted correction based on the reviewer's feedback.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update: {"articles": [...], "cost_tracker": {...}}.
    """
    iteration = state.get("iteration", 0)
    logger.info("[OrganizeNode] Starting organization (iteration=%d)", iteration)

    articles: list[dict] = state.get("articles", [])
    review_feedback: str = state.get("review_feedback", "")
    cost_tracker: dict = state.get("cost_tracker") or {}

    if not articles:
        logger.warning("[OrganizeNode] No articles to organize")
        return {"articles": []}

    # Step 1 — URL 去重
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for article in articles:
        url = article.get("source_url", "")
        if url not in seen_urls:
            seen_urls.add(url)
            deduped.append(article)
        else:
            logger.info("[OrganizeNode] Duplicate removed: %s", article.get("title", ""))
    logger.info("[OrganizeNode] Dedup: %d → %d", len(articles), len(deduped))

    # Step 2 — 过滤低分条目（需求 <0.6，1-10 制换算为 < 6）
    filtered: list[dict] = [
        a for a in deduped if a.get("relevance_score", 0) >= RELEVANCE_MIN
    ]
    logger.info(
        "[OrganizeNode] Relevance filter (>=%d): %d → %d",
        RELEVANCE_MIN, len(deduped), len(filtered),
    )

    # Step 3 — iteration > 0 且有反馈时，调用 LLM 做定向修正
    if iteration > 0 and review_feedback:
        logger.info("[OrganizeNode] Applying LLM corrections based on review feedback")

        try:
            client = create_client()
        except ValueError as e:
            logger.error("[OrganizeNode] Failed to create LLM client: %s", e)
            return {"articles": filtered, "cost_tracker": cost_tracker}

        corrected: list[dict] = []
        for article in filtered:
            prompt = f"""根据以下审核反馈，修正该知识条目。只输出修正后的完整JSON对象。

原条目：
{json.dumps(article, ensure_ascii=False, indent=2)}

审核反馈：
{review_feedback}

请修正 summary、tags、category 或 relevance_score，其他字段保持不变。
只输出JSON对象，不要任何其他文字。"""

            try:
                messages = [
                    {"role": "system", "content": CORRECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
                response = client.chat_with_retry(messages, max_tokens=1000)
                fixed = _parse_json_response(response.content)

                # 强制保留不可变字段
                for key in ("id", "source_url", "source", "collected_at", "status", "published_at"):
                    if key in article:
                        fixed[key] = article[key]

                corrected.append(fixed)
                accumulate_usage(cost_tracker, response.usage)
                logger.info("[OrganizeNode] Corrected: %s", fixed.get("title", ""))

            except Exception as e:
                logger.warning(
                    "[OrganizeNode] Correction failed for %s, keeping original: %s",
                    article.get("title", ""), e,
                )
                corrected.append(article)

        filtered = corrected
        cost_tracker["estimated_cost_usd"] = _compute_cost(cost_tracker, client.provider)

    return {
        "articles": filtered,
        "cost_tracker": cost_tracker,
    }


# ---------------------------------------------------------------------------
# 节点 4: REVIEW_NODE — 四维度 LLM 评分和审核决策
# ---------------------------------------------------------------------------


def review_node(state: KBState) -> dict:
    """Review articles with LLM scoring across 4 dimensions.

    LLM output schema:
        {"passed": bool, "overall_score": float, "feedback": str, "scores": {...}}

    Forces pass when iteration >= 2 to prevent infinite loops.

    Args:
        state: Current workflow state.

    Returns:
        Partial state update: {"review_passed": bool, "review_feedback": str,
                               "iteration": int, "cost_tracker": {...}}.
    """
    iteration = state.get("iteration", 0)
    logger.info("[ReviewNode] Starting review (iteration=%d)", iteration)

    articles: list[dict] = state.get("articles", [])
    cost_tracker: dict = state.get("cost_tracker") or {}

    if not articles:
        logger.warning("[ReviewNode] No articles to review, auto-passing")
        return {"review_passed": True, "review_feedback": "", "iteration": iteration + 1}

    # iteration >= 2 强制通过，避免无限循环
    if iteration >= 2:
        logger.info("[ReviewNode] iteration >= 2: forcing pass")
        return {
            "review_passed": True,
            "review_feedback": "Force-passed after reaching max iterations.",
            "iteration": iteration + 1,
        }

    try:
        client = create_client()
    except ValueError as e:
        logger.error("[ReviewNode] Failed to create LLM client: %s", e)
        return {
            "review_passed": False,
            "review_feedback": f"LLM client error: {e}",
            "iteration": iteration,
        }

    articles_payload = json.dumps(
        [
            {
                "id": a.get("id"),
                "title": a.get("title"),
                "summary": a.get("summary"),
                "tags": a.get("tags"),
                "category": a.get("category"),
                "relevance_score": a.get("relevance_score"),
            }
            for a in articles
        ],
        ensure_ascii=False,
        indent=2,
    )

    prompt = f"""请评审以下知识库条目，按4个维度评分（1-10分）并给出整体决策。

维度说明：
1. 摘要质量（summary_quality）：摘要是否准确、完整、清晰
2. 标签准确（tag_accuracy）：标签是否准确反映内容
3. 分类合理（category_reasonableness）：分类是否符合实际
4. 一致性（consistency）：标题、摘要、标签之间的逻辑一致性

条目列表：
{articles_payload}

输出一个JSON对象：
{{
  "passed": true,
  "overall_score": 8.0,
  "feedback": "具体改进建议（中文，如无需改进可写'内容质量良好'）",
  "scores": {{
    "summary_quality": 8,
    "tag_accuracy": 7,
    "category_reasonableness": 9,
    "consistency": 8
  }}
}}

passed=true 表示质量合格可保存；false 表示需要修正。
只输出JSON对象，不要markdown代码块或其他文字。"""

    try:
        messages = [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        response = client.chat_with_retry(messages, max_tokens=1000)
        review_result = _parse_json_response(response.content)

        passed: bool = bool(review_result.get("passed", False))
        feedback: str = str(review_result.get("feedback", ""))
        overall_score: float = float(review_result.get("overall_score", 5.0))

        accumulate_usage(cost_tracker, response.usage)
        cost_tracker["estimated_cost_usd"] = _compute_cost(cost_tracker, client.provider)

        logger.info(
            "[ReviewNode] Result: passed=%s, overall_score=%.1f", passed, overall_score
        )
        logger.info("[ReviewNode] Feedback: %s", feedback)

        return {
            "review_passed": passed,
            "review_feedback": feedback,
            "iteration": iteration + 1,
            "cost_tracker": cost_tracker,
        }

    except Exception as e:
        logger.error("[ReviewNode] Review failed, defaulting to pass: %s", e)
        return {
            "review_passed": True,
            "review_feedback": f"Review error (auto-pass): {e}",
            "iteration": iteration + 1,
            "cost_tracker": cost_tracker,
        }


# ---------------------------------------------------------------------------
# 节点 5: SAVE_NODE — 保存到知识库并更新索引
# ---------------------------------------------------------------------------


def save_node(state: KBState) -> dict:
    """Save articles to individual JSON files and update knowledge/articles/index.json.

    Each article is written to:
        knowledge/articles/YYYYMMDD-{source}-{slug}.json

    The index (index.json) is updated with one lightweight entry per article.
    Existing entries with the same id are not duplicated.

    Args:
        state: Current workflow state.

    Returns:
        Empty dict (terminal node, no state changes required).
    """
    logger.info("[SaveNode] Starting save operation")

    articles: list[dict] = state.get("articles", [])
    if not articles:
        logger.warning("[SaveNode] No articles to save")
        return {}

    _ensure_dirs()

    new_entries: list[dict] = []
    saved_count = 0

    for article in articles:
        try:
            article_id = article.get("id", f"unknown-{saved_count:03d}")
            slug = _slugify(article.get("title", article_id))
            source = article.get("source", "unknown")
            filename = f"{_today_str()}-{source}-{slug}.json"
            article_file = ARTICLES_DIR / filename

            with open(article_file, "w", encoding="utf-8") as f:
                json.dump(article, f, ensure_ascii=False, indent=2)

            new_entries.append({
                "id": article_id,
                "title": article.get("title", ""),
                "source": source,
                "category": article.get("category", ""),
                "relevance_score": article.get("relevance_score", 0),
                "status": article.get("status", "draft"),
                "file": filename,
                "saved_at": _now_iso(),
            })
            saved_count += 1
            logger.info("[SaveNode] Saved: %s → %s", article_id, filename)

        except Exception as e:
            logger.error(
                "[SaveNode] Failed to save article %s: %s", article.get("id", "?"), e
            )

    # 读取现有索引，按 id 去重合并，最新在前
    existing_index: list[dict] = []
    if INDEX_FILE.exists():
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                existing_index = json.load(f)
        except Exception as e:
            logger.warning("[SaveNode] Could not read existing index: %s", e)

    existing_ids = {e["id"] for e in existing_index}
    for entry in new_entries:
        if entry["id"] not in existing_ids:
            existing_index.append(entry)
            existing_ids.add(entry["id"])

    existing_index.sort(key=lambda x: x.get("saved_at", ""), reverse=True)

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_index, f, ensure_ascii=False, indent=2)

    logger.info(
        "[SaveNode] Saved %d articles; index now has %d entries",
        saved_count, len(existing_index),
    )
    return {}
