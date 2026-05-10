#!/usr/bin/env python3
"""Four-step AI knowledge base automation pipeline.

Collect → Analyze → Organize → Save

Usage:
    python pipeline/pipeline.py --sources github,rss --limit 20
    python pipeline/pipeline.py --sources github --limit 5
    python pipeline/pipeline.py --sources rss --limit 10
    python pipeline/pipeline.py --sources github --limit 5 --dry-run
    python pipeline/pipeline.py --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Project root discovery (robust, works regardless of how script is invoked)
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    """Locate the project root directory by walking up from this file or CWD.

    Uses AGENTS.md as the anchor file to detect the project root.
    Falls back to __file__-based resolution.

    Returns:
        Absolute Path to the project root.
    """
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
_PIPELINE_DIR = _PROJECT_ROOT / "pipeline"

sys.path.insert(0, str(_PIPELINE_DIR))
from model_client import create_client  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CST = timezone(timedelta(hours=8))

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_SORT = "stars"
GITHUB_ORDER = "desc"
GITHUB_PER_PAGE = 30
GITHUB_TIMEOUT = 30.0

AI_KEYWORDS_RE = re.compile(
    r"\b(ai|llm|agent|gpt|openai|deepseek|qwen|claude|transformer|"
    r"rag|langchain|llama|mistral|gemini|neural|diffusion|"
    r"nlp|machine.learning|deep.learning|prompt)\b",
    re.IGNORECASE,
)

RSS_FEEDS: dict[str, str] = {
    "hackernews": "https://hnrss.org/frontpage?count=30",
    "arxiv_cs_ai": "https://rss.arxiv.org/rss/cs.AI",
}
RSS_TIMEOUT = 30.0

RAW_DIR = _PROJECT_ROOT / "knowledge" / "raw"
ARTICLES_DIR = _PROJECT_ROOT / "knowledge" / "articles"
PROCESSED_DIR = ARTICLES_DIR / ".processed"

VALID_CATEGORIES = frozenset(
    {"model_release", "agent_framework", "tool", "paper", "opinion"}
)
VALID_SENTIMENTS = frozenset({"positive", "neutral", "negative"})
TITLE_SIMILARITY_THRESHOLD = 0.85
RELEVANCE_MIN = 5

COLLECT_RETRY_MAX = 3
COLLECT_RETRY_BASE = 1.0

ANALYSIS_SYSTEM_PROMPT = (
    "你是一个AI技术分析专家。请严格按以下JSON格式输出分析结果，"
    "不要输出任何其他文字、代码块标记或解释。"
)

ANALYSIS_USER_TEMPLATE = """分析以下GitHub项目并输出一个JSON对象：

名称：{name}
描述：{description}
语言：{language}
标签：{topics}
星数：{stars}

输出格式：
{{
  "title": "中文标题（30字以内，含项目名，吸引人但不浮夸）",
  "summary": "中文摘要，1-3句，涵盖核心价值和创新点（50-150字）",
  "tags": ["标签1", "标签2", "标签3", "标签4", "标签5"],
  "category": "model_release/agent_framework/tool/paper/opinion",
  "relevance_score": 1-10,
  "key_points": ["要点1", "要点2", "要点3", "要点4", "要点5"],
  "sentiment": "positive/neutral/negative"
}}

评分参考：
- 10: 里程碑式（GPT-5发布等）
- 8-9: 非常重要（主流框架大更新）
- 6-7: 重要（有趣的新项目/工具）
- 4-5: 一般相关
- 1-3: 边缘相关

只输出JSON对象，不要markdown代码块。"""

RSS_ANALYSIS_USER_TEMPLATE = """分析以下技术文章并输出一个JSON对象：

标题：{title}
链接：{link}
摘要：{description}
来源：{source}

输出格式：
{{
  "title": "中文标题（30字以内，保留核心信息）",
  "summary": "中文摘要，1-3句，涵盖文章核心观点（50-150字）",
  "tags": ["标签1", "标签2", "标签3", "标签4", "标签5"],
  "category": "model_release/agent_framework/tool/paper/opinion",
  "relevance_score": 1-10,
  "key_points": ["要点1", "要点2", "要点3", "要点4", "要点5"],
  "sentiment": "positive/neutral/negative"
}}

只输出JSON对象，不要markdown代码块。"""


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """Return current time in ISO 8601 with CST offset."""
    return datetime.now(CST).isoformat()


def today_str() -> str:
    """Return today's date as YYYYMMDD in CST."""
    return datetime.now(CST).strftime("%Y%m%d")


def slugify(text: str, max_len: int = 60) -> str:
    """Generate a URL/filesystem-safe slug from text.

    Args:
        text: Input text (e.g. repo name or title).
        max_len: Maximum slug length.

    Returns:
        Lowercase hyphenated slug.
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_len].strip("-")


def _char_ngrams(s: str, n: int = 3) -> set[str]:
    """Extract character n-grams from a string."""
    s = s.lower()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def title_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity between two titles using character trigrams.

    Args:
        a: First title string.
        b: Second title string.

    Returns:
        Similarity score in [0.0, 1.0].
    """
    if not a or not b:
        return 0.0
    set_a = _char_ngrams(a, 3)
    set_b = _char_ngrams(b, 3)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _parse_json_response(raw: str) -> dict[str, Any]:
    """Extract a JSON object from LLM response text.

    Handles ```json fences and leading/trailing noise.

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
        text = m.group(1)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise json.JSONDecodeError("No JSON object found in response", raw, 0)


def ensure_dirs() -> None:
    """Create required output directories if they don't exist."""
    for d in (RAW_DIR, ARTICLES_DIR, PROCESSED_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Step 1 — Collect
# ---------------------------------------------------------------------------


def _fetch_github_trending(limit: int) -> list[dict[str, Any]]:
    """Fetch AI-related trending repos from GitHub Search API.

    Args:
        limit: Maximum number of items to return.

    Returns:
        List of raw trending item dicts.

    Raises:
        RuntimeError: If all retry attempts are exhausted.
    """
    params: dict[str, str | int] = {
        "q": "ai OR llm OR agent OR gpt OR openai topics:>=1",
        "sort": GITHUB_SORT,
        "order": GITHUB_ORDER,
        "per_page": min(limit, GITHUB_PER_PAGE),
    }
    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    if token := os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    last_error: Exception | None = None
    for attempt in range(1, COLLECT_RETRY_MAX + 1):
        try:
            logger.info(
                "GitHub Search API request (attempt %d/%d): %s",
                attempt,
                COLLECT_RETRY_MAX,
                params["q"],
            )
            resp = httpx.get(
                GITHUB_SEARCH_URL,
                params=params,
                headers=headers,
                timeout=GITHUB_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            items: list[dict[str, Any]] = []
            for item in data.get("items", [])[:limit]:
                items.append(
                    {
                        "name": item.get("full_name", ""),
                        "url": item.get("html_url", ""),
                        "description": item.get("description") or "",
                        "stars": item.get("stargazers_count", 0),
                        "language": item.get("language") or "",
                        "topics": item.get("topics", []),
                    }
                )
            logger.info("GitHub: fetched %d repos", len(items))
            return items
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            last_error = e
            if attempt == COLLECT_RETRY_MAX:
                break
            delay = COLLECT_RETRY_BASE * (2 ** (attempt - 1))
            logger.warning(
                "GitHub fetch failed (attempt %d/%d): %s. Retrying in %.1fs…",
                attempt,
                COLLECT_RETRY_MAX,
                e,
                delay,
            )
            time.sleep(delay)

    logger.error("GitHub fetch failed after %d retries: %s", COLLECT_RETRY_MAX, last_error)
    raise RuntimeError("GitHub fetch exhausted all retries") from last_error


def _fetch_rss(source_name: str, feed_url: str, limit: int) -> list[dict[str, Any]]:
    """Fetch and parse an RSS feed, filtering for AI-related entries.

    Uses simple regex-based XML parsing as specified.

    Args:
        source_name: Human-readable source name for logging.
        feed_url: RSS feed URL.
        limit: Maximum number of items to return.

    Returns:
        List of raw RSS item dicts.

    Raises:
        RuntimeError: If all retry attempts are exhausted.
    """
    last_error: Exception | None = None
    for attempt in range(1, COLLECT_RETRY_MAX + 1):
        try:
            logger.info(
                "RSS fetch %s (attempt %d/%d): %s",
                source_name,
                attempt,
                COLLECT_RETRY_MAX,
                feed_url,
            )
            resp = httpx.get(feed_url, timeout=RSS_TIMEOUT)
            resp.raise_for_status()
            xml_text = resp.text

            items: list[dict[str, Any]] = []
            item_blocks = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)
            for block in item_blocks:
                title_m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.DOTALL)
                link_m = re.search(r"<link>(.*?)</link>", block, re.DOTALL)
                desc_m = re.search(
                    r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>",
                    block,
                    re.DOTALL,
                )

                title = title_m.group(1).strip() if title_m else ""
                link = link_m.group(1).strip() if link_m else ""
                description = desc_m.group(1).strip() if desc_m else ""

                if not title or not link:
                    continue

                combined = f"{title} {description}"
                if not AI_KEYWORDS_RE.search(combined):
                    continue

                items.append(
                    {
                        "name": title,
                        "url": link,
                        "description": description,
                        "stars": 0,
                        "language": "",
                        "topics": [],
                    }
                )

            logger.info("RSS %s: fetched %d AI-related items", source_name, len(items))
            return items[:limit]

        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            last_error = e
            if attempt == COLLECT_RETRY_MAX:
                break
            delay = COLLECT_RETRY_BASE * (2 ** (attempt - 1))
            logger.warning(
                "RSS fetch %s failed (attempt %d/%d): %s. Retrying in %.1fs…",
                source_name,
                attempt,
                COLLECT_RETRY_MAX,
                e,
                delay,
            )
            time.sleep(delay)

    logger.error("RSS %s fetch failed after %d retries: %s", source_name, COLLECT_RETRY_MAX, last_error)
    raise RuntimeError(f"RSS {source_name} fetch exhausted all retries") from last_error


def collect(sources: list[str], limit: int) -> dict[str, Any]:
    """Run the collection step for specified sources.

    Args:
        sources: List of source identifiers (github, rss feed names).
        limit: Maximum items per source.

    Returns:
        Combined raw data dict ready for the analyze step.
        Contains source, collected_at, items, and errors.

    Raises:
        RuntimeError: If all sources fail.
    """
    all_items: list[dict[str, Any]] = []
    source_label_parts: list[str] = []
    errors: list[str] = []
    collected_at = now_iso()

    for src in sources:
        try:
            if src == "github":
                items = _fetch_github_trending(limit)
                for it in items:
                    it["_source"] = "github"
                all_items.extend(items)
                source_label_parts.append("github")
                logger.info("Collect github: %d items", len(items))
            elif src in RSS_FEEDS:
                items = _fetch_rss(src, RSS_FEEDS[src], limit)
                for it in items:
                    it["_source"] = src
                all_items.extend(items)
                source_label_parts.append(src)
                logger.info("Collect %s: %d items", src, len(items))
            else:
                logger.warning("Unknown source: %s", src)
        except RuntimeError as e:
            logger.error("Source %s failed: %s", src, e)
            errors.append(f"{src}: {e}")

    if not all_items and not errors:
        raise RuntimeError("No items collected from any source")
    if errors and len(errors) == len(sources):
        raise RuntimeError(f"All sources failed: {'; '.join(errors)}")

    source_label = "_".join(source_label_parts) if source_label_parts else "unknown"
    filename = f"{source_label}_{today_str()}_{datetime.now(CST).strftime('%H%M%S')}.json"
    filepath = RAW_DIR / filename

    raw_data: dict[str, Any] = {
        "source": source_label,
        "collected_at": collected_at,
        "items": all_items,
    }
    if errors:
        raw_data["errors"] = errors

    filepath.write_text(json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Raw data saved: %s (%d items)", filepath.name, len(all_items))
    return raw_data


# ---------------------------------------------------------------------------
# Step 2 — Analyze
# ---------------------------------------------------------------------------


def _analyze_single(
    client: Any,
    item: dict[str, Any],
    source: str,
    is_rss: bool,
) -> dict[str, Any]:
    """Analyze a single item via LLM call.

    HTTP-level retry is handled by client.chat_with_retry.

    Args:
        client: An OpenAICompatibleProvider instance.
        item: Raw collected item dict.
        source: Source identifier string.
        is_rss: Whether the item came from an RSS feed.

    Returns:
        Article dict with AI analysis fields populated, or with
        status="analysis_failed" if the LLM call or JSON parsing fails.
    """
    collected_at = item.get("_collected_at", now_iso())
    source_url = item.get("url", "")

    if is_rss:
        user_prompt = RSS_ANALYSIS_USER_TEMPLATE.format(
            title=item.get("name", ""),
            link=source_url,
            description=item.get("description", ""),
            source=source,
        )
    else:
        user_prompt = ANALYSIS_USER_TEMPLATE.format(
            name=item.get("name", ""),
            description=item.get("description", ""),
            language=item.get("language", ""),
            topics=", ".join(item.get("topics", [])),
            stars=item.get("stars", 0),
        )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = client.chat_with_retry(
            messages, temperature=0.3, max_tokens=2048
        )
        parsed = _parse_json_response(response.content)

        score = int(parsed.get("relevance_score", 5))
        score = max(1, min(10, score))

        category = parsed.get("category", "tool")
        if category not in VALID_CATEGORIES:
            category = "tool"

        sentiment = parsed.get("sentiment", "neutral")
        if sentiment not in VALID_SENTIMENTS:
            sentiment = "neutral"

        return {
            "title": str(parsed.get("title", item.get("name", ""))),
            "source_url": source_url,
            "summary": str(parsed.get("summary", "")),
            "tags": [str(t) for t in parsed.get("tags", [])[:5]],
            "category": category,
            "status": "draft",
            "collected_at": collected_at,
            "published_at": None,
            "ai_analysis": {
                "relevance_score": score,
                "key_points": [str(p) for p in parsed.get("key_points", [])[:5]],
                "sentiment": sentiment,
            },
        }
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(
            "LLM analysis failed for '%s': %s",
            item.get("name", "?"),
            e,
        )

    logger.error(
        "Analysis exhausted for '%s', marking as analysis_failed",
        item.get("name", "?"),
    )
    return {
        "title": str(item.get("name", "")),
        "source_url": source_url,
        "summary": item.get("description", ""),
        "tags": [],
        "category": "tool",
        "status": "analysis_failed",
        "collected_at": collected_at,
        "published_at": None,
        "ai_analysis": None,
    }


def analyze(raw_data: dict[str, Any], dry_run: bool = False) -> list[dict[str, Any]]:
    """Run AI analysis on collected items.

    Args:
        raw_data: Output from the collect step.
        dry_run: If True, skip LLM calls and return stub entries.

    Returns:
        List of article dicts with AI analysis.

    Raises:
        ValueError: If no API key is configured and not in dry-run mode.
    """
    items: list[dict[str, Any]] = raw_data.get("items", [])
    if not items:
        logger.warning("No items to analyze")
        return []

    source = raw_data.get("source", "unknown")
    collected_at = raw_data.get("collected_at", now_iso())

    for item in items:
        item["_collected_at"] = collected_at

    if dry_run:
        logger.info("Dry-run: skipping LLM calls, producing stub analysis for %d items", len(items))
        results: list[dict[str, Any]] = []
        for item in items:
            results.append(
                {
                    "title": str(item.get("name", "")),
                    "source_url": item.get("url", ""),
                    "summary": f"[DRY-RUN] {item.get('description', '')[:100]}",
                    "tags": [],
                    "category": "tool",
                    "status": "draft",
                    "collected_at": collected_at,
                    "published_at": None,
                    "ai_analysis": {"relevance_score": 5, "key_points": [], "sentiment": "neutral"},
                }
            )
        return results

    api_key = (
        os.getenv("LLM_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("QWEN_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if not api_key:
        raise ValueError(
            "No LLM API key configured. Set DEEPSEEK_API_KEY, QWEN_API_KEY, "
            "OPENAI_API_KEY, or LLM_API_KEY in .env, or use --dry-run."
        )

    client = create_client()
    logger.info("Analyzing %d items with provider=%s", len(items), client.provider)

    articles: list[dict[str, Any]] = []
    success_count = 0
    fail_count = 0

    for i, item in enumerate(items, 1):
        item_source = item.get("_source", source)
        is_rss = item_source not in ("github", "github_trending")
        logger.info("Analyzing [%d/%d]: %s", i, len(items), item.get("name", "?"))
        article = _analyze_single(client, item, item_source, is_rss)
        if article["status"] == "analysis_failed":
            fail_count += 1
        else:
            success_count += 1
        articles.append(article)

    logger.info(
        "Analysis complete: %d success, %d failed, %d total",
        success_count,
        fail_count,
        len(articles),
    )

    analysis_batch = ARTICLES_DIR / f"{today_str()}-{source}-analysis.json"
    analysis_batch.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Analysis batch saved: %s", analysis_batch.name)

    return articles


# ---------------------------------------------------------------------------
# Step 3 — Organize
# ---------------------------------------------------------------------------


def organize(
    articles: list[dict[str, Any]],
    raw_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Deduplicate, standardize, and validate articles.

    Steps:
        1. Dedup by exact URL match.
        2. Dedup by title trigram similarity (threshold 0.85).
        3. Assign unique IDs (format: {source_short}-{YYYYMMDD}-{NNN}).
        4. Validate required fields and fill defaults.
        5. Filter out low-relevance entries (relevance_score < 5).

    Args:
        articles: Article list from the analyze step.
        raw_data: Original raw data for source/date context.

    Returns:
        Deduplicated, validated, ID-assigned article list.
    """
    if not articles:
        logger.warning("No articles to organize")
        return []

    source_label = raw_data.get("source", "unknown")
    source_short = "github" if "github" in source_label else "hn"
    date_str = today_str()

    # --- Dedup by URL ---
    seen_urls: set[str] = set()
    unique_by_url: list[dict[str, Any]] = []
    for art in articles:
        url = art.get("source_url", "")
        if url and url in seen_urls:
            logger.debug("Dedup (URL): %s", url)
            continue
        seen_urls.add(url)
        unique_by_url.append(art)
    if len(unique_by_url) < len(articles):
        logger.info("URL dedup: %d → %d", len(articles), len(unique_by_url))

    # --- Dedup by title similarity ---
    deduped: list[dict[str, Any]] = []
    for art in unique_by_url:
        title = art.get("title", "")
        is_dup = False
        for existing in deduped:
            existing_title = existing.get("title", "")
            sim = title_similarity(title, existing_title)
            if sim >= TITLE_SIMILARITY_THRESHOLD:
                logger.debug(
                    "Dedup (title similarity=%.2f): '%s' ≈ '%s'",
                    sim,
                    title[:40],
                    existing_title[:40],
                )
                is_dup = True
                break
        if not is_dup:
            deduped.append(art)
    if len(deduped) < len(unique_by_url):
        logger.info("Title dedup: %d → %d", len(unique_by_url), len(deduped))

    # --- Assign IDs ---
    for idx, art in enumerate(deduped, 1):
        art["id"] = f"{source_short}-{date_str}-{idx:03d}"

    # --- Validate & normalize ---
    validated: list[dict[str, Any]] = []
    filtered_low_score = 0
    for art in deduped:
        # Fill defaults
        art.setdefault("source", source_label)
        art.setdefault("status", "draft")
        art.setdefault("category", "tool")
        art.setdefault("tags", [])
        art.setdefault("collected_at", raw_data.get("collected_at", now_iso()))
        art.setdefault("published_at", None)
        art.setdefault("title", "Untitled")
        art.setdefault("source_url", "")
        art.setdefault("summary", "")
        if "ai_analysis" not in art:
            art["ai_analysis"] = None

        # Filter low relevance
        score = (
            art.get("ai_analysis", {}).get("relevance_score", 0)
            if isinstance(art.get("ai_analysis"), dict)
            else 0
        )
        if score < RELEVANCE_MIN:
            art["status"] = "archived"
            filtered_low_score += 1

        validated.append(art)

    if filtered_low_score:
        logger.info("Archived %d low-relevance entries (score < %d)", filtered_low_score, RELEVANCE_MIN)

    logger.info(
        "Organize complete: %d articles (from %d raw, %d archived)",
        len(validated),
        len(articles),
        filtered_low_score,
    )
    return validated


# ---------------------------------------------------------------------------
# Step 4 — Save
# ---------------------------------------------------------------------------


def save(
    articles: list[dict[str, Any]],
    raw_data: dict[str, Any],
    dry_run: bool = False,
) -> None:
    """Write each article as an individual JSON file to knowledge/articles/.

    Also archives the analysis batch file to .processed/.

    Args:
        articles: Organized article list from the organize step.
        raw_data: Raw data dict (for source/date context).
        dry_run: If True, only log what would be written.
    """
    if not articles:
        logger.warning("No articles to save")
        return

    source_label = raw_data.get("source", "unknown")
    date_str = today_str()

    if dry_run:
        logger.info("[DRY-RUN] Would write %d articles to %s", len(articles), ARTICLES_DIR)
        for art in articles:
            art_id = art.get("id", "?")
            title = art.get("title", "?")[:50]
            status = art.get("status", "?")
            score = (
                art.get("ai_analysis", {}).get("relevance_score", "?")
                if isinstance(art.get("ai_analysis"), dict)
                else "?"
            )
            logger.info("  [DRY-RUN] %s | score=%s | %s | %s", art_id, score, status, title)
        return

    ensure_dirs()

    written = 0
    skipped = 0

    for art in articles:
        art_id = art.get("id", "")
        title = art.get("title", "Untitled")
        source_short = "github" if "github" in source_label else "hn"
        slug = slugify(title) or "untitled"
        filename = f"{date_str}-{source_short}-{slug}.json"
        filepath = ARTICLES_DIR / filename

        # Avoid overwriting existing files
        if filepath.exists():
            logger.debug("Skip existing: %s", filename)
            skipped += 1
            continue

        filepath.write_text(
            json.dumps(art, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved: %s (%s)", filename, art_id)
        written += 1

    logger.info("Save complete: %d written, %d skipped, %d total", written, skipped, len(articles))

    # Archive the analysis batch
    analysis_batch = ARTICLES_DIR / f"{date_str}-{source_label}-analysis.json"
    if analysis_batch.exists():
        target = PROCESSED_DIR / analysis_batch.name
        analysis_batch.rename(target)
        logger.info("Archived analysis batch → %s", target.name)


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def run_pipeline(
    sources: list[str],
    limit: int,
    dry_run: bool = False,
) -> int:
    """Execute the full four-step pipeline.

    Args:
        sources: Source identifiers (github, hackernews, arxiv_cs_ai).
        limit: Maximum items per source.
        dry_run: If True, skip API calls and file writes.

    Returns:
        Exit code (0 = success, 1 = error).
    """
    logger.info("=" * 60)
    logger.info("Pipeline started — sources=%s, limit=%d, dry_run=%s", sources, limit, dry_run)
    logger.info("=" * 60)

    try:
        ensure_dirs()

        # Step 1: Collect
        logger.info("--- Step 1: Collect ---")
        raw_data = collect(sources, limit)
        if not raw_data.get("items"):
            logger.warning("No items collected, stopping pipeline")
            return 0

        # Step 2: Analyze
        logger.info("--- Step 2: Analyze ---")
        articles = analyze(raw_data, dry_run=dry_run)
        if not articles:
            logger.warning("No articles produced, stopping pipeline")
            return 0

        # Step 3: Organize
        logger.info("--- Step 3: Organize ---")
        organized = organize(articles, raw_data)
        if not organized:
            logger.warning("No articles after organization, stopping pipeline")
            return 0

        # Step 4: Save
        logger.info("--- Step 4: Save ---")
        save(organized, raw_data, dry_run=dry_run)

        logger.info("=" * 60)
        logger.info("Pipeline completed successfully")
        logger.info("=" * 60)
        return 0

    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user")
        return 1
    except Exception:
        logger.exception("Pipeline failed with unhandled error")
        return 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list; defaults to sys.argv[1:].

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(
        description="AI Knowledge Base — four-step automation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python pipeline/pipeline.py --sources github,rss --limit 20\n"
            "  python pipeline/pipeline.py --sources github --limit 5\n"
            "  python pipeline/pipeline.py --sources rss --limit 10\n"
            "  python pipeline/pipeline.py --sources github --limit 5 --dry-run\n"
            "  python pipeline/pipeline.py --verbose"
        ),
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="github",
        help=(
            "Comma-separated source identifiers. "
            "Built-in: github, hackernews, arxiv_cs_ai. "
            "Use 'rss' as alias for all RSS feeds. "
            "(default: github)"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Maximum items to fetch per source (default: 15)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run mode: collect data but skip LLM analysis and file writes",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    parser.add_argument(
        "--output-raw",
        action="store_true",
        help="Print raw collected data to stdout as JSON and exit (skips analysis+)",
    )
    return parser.parse_args(argv)


def _resolve_sources(raw_sources: str) -> list[str]:
    """Resolve comma-separated source names, expanding 'rss' alias.

    Args:
        raw_sources: Comma-separated source names from --sources.

    Returns:
        Deduplicated list of valid source identifiers.
    """
    parts = [s.strip().lower() for s in raw_sources.split(",") if s.strip()]
    resolved: list[str] = []
    for p in parts:
        if p == "rss":
            for name in RSS_FEEDS:
                if name not in resolved:
                    resolved.append(name)
        elif p in ("github", "github_trending", "gh"):
            if "github" not in resolved:
                resolved.append("github")
        elif p in RSS_FEEDS:
            if p not in resolved:
                resolved.append(p)
        else:
            logger.warning("Unknown source '%s', skipping", p)
    return resolved


def main(argv: list[str] | None = None) -> None:
    """Entry point for the pipeline CLI."""
    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sources = _resolve_sources(args.sources)
    if not sources:
        logger.error("No valid sources specified")
        sys.exit(2)

    logger.debug("Resolved sources: %s", sources)

    if args.output_raw:
        ensure_dirs()
        raw_data = collect(sources, args.limit)
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(json.dumps(raw_data, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
        sys.exit(0)

    exit_code = run_pipeline(
        sources=sources,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
