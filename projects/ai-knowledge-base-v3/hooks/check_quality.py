#!/usr/bin/env python3
"""Quality scoring for knowledge base articles across 5 dimensions.

Usage:
    python hooks/check_quality.py <json_file> [json_file2 ...]
    python hooks/check_quality.py --no-color <json_file> [...]

Supports single files, multiple files, and wildcard patterns (e.g. *.json).
Exit 0 if all articles grade A/B, exit 1 if any article grades C.
"""

import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANSI color helpers (no third-party dependencies)
# ---------------------------------------------------------------------------

_USE_COLOR = True


def _detect_color() -> bool:
    """Detect whether the terminal supports ANSI color output."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not sys.stdout.isatty():
        return False
    plat = sys.platform
    if plat == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return True
        except Exception:
            pass
        return "ANSICON" in os.environ or "WT_SESSION" in os.environ
    return True


# Palette
_C = {
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "blue": "\033[34m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def _color(code: str, text: str) -> str:
    """Wrap *text* in an ANSI color code if color is enabled."""
    if not _USE_COLOR or code not in _C:
        return text
    return f"{_C[code]}{text}{_C['reset']}"


def _grade_color(grade: str) -> str:
    """Return the color key for a letter grade."""
    if grade == "A":
        return "green"
    if grade == "B":
        return "yellow"
    return "red"


def _ratio_color(ratio: float) -> str:
    """Return the color key for a score ratio (0.0-1.0)."""
    if ratio >= 0.8:
        return "green"
    if ratio >= 0.5:
        return "yellow"
    return "red"

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DimensionScore:
    """Score for a single quality dimension."""

    name: str
    score: float
    max_score: float
    details: str = ""


@dataclass
class QualityReport:
    """Full quality report for one article."""

    filepath: str
    total_score: float
    dimensions: list[DimensionScore]
    grade: str


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CN_BUZZWORDS: set[str] = {
    "赋能",
    "抓手",
    "闭环",
    "打通",
    "全链路",
    "底层逻辑",
    "颗粒度",
    "对齐",
    "拉通",
    "沉淀",
    "强大的",
}

_EN_BUZZWORDS: set[str] = {
    "groundbreaking",
    "revolutionary",
    "game-changing",
    "cutting-edge",
    "disruptive",
    "paradigm-shift",
    "next-generation",
    "best-in-class",
    "world-class",
    "state-of-the-art",
}

_TECH_KEYWORDS: set[str] = {
    "LLM",
    "Agent",
    "RAG",
    "API",
    "Python",
    "AI",
    "\u6a21\u578b",
    "\u63a8\u7406",
    "\u8bad\u7ec3",
    "\u5f00\u6e90",
    "\u6846\u67b6",
    "\u5411\u91cf",
    "\u5d4c\u5165",
    "\u5fae\u8c03",
    "\u90e8\u7f72",
    "\u591a\u6a21\u6001",
    "Transformer",
    "GPT",
    "Claude",
    "OpenAI",
    "\u6269\u6563",
    "\u68c0\u7d22",
    "\u751f\u6210",
    "Pipeline",
    "Tool",
    "MCP",
    "\u8c03\u7528",
    "\u8bc4\u4f30",
    "\u6570\u636e\u96c6",
    "Docker",
}

_STANDARD_TAGS: set[str] = {
    "LLM",
    "Agent",
    "RAG",
    "OpenSource",
    "API",
    "Python",
    "TypeScript",
    "Rust",
    "Go",
    "AI",
    "MachineLearning",
    "DeepLearning",
    "NLP",
    "ComputerVision",
    "GPT",
    "Claude",
    "OpenAI",
    "Anthropic",
    "Tool",
    "Framework",
    "Library",
    "Pipeline",
    "TUI",
    "CLI",
    "WebUI",
    "ChatBot",
    "CodingAgent",
    "DeveloperTools",
    "MultiModel",
    "VectorDB",
    "Embedding",
    "FineTuning",
    "PromptEngineering",
    "Evaluation",
    "Deployment",
    "Docker",
    "Kubernetes",
    "GitHub",
    "MCP",
    "Transformer",
    "Diffusion",
    "Inference",
    "Training",
    "Benchmark",
    "Cognition",
    "Autonomous",
    "Workflow",
    "Orchestration",
    "AIAssistant",
    "MultiChannel",
    "SelfHosted",
    "Skills",
    "Gateway",
    "Vision",
    "Audio",
    "Voice",
    "SpeechToText",
    "TextToSpeech",
    "LangChain",
    "LangFlow",
    "Ollama",
    "Dify",
    "n8n",
    "AutoGPT",
    "VideoGeneration",
    "CodeGeneration",
    "Prompt",
    "ChatCompletion",
}

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*-\d{8}-\d{3}$")
_URL_PATTERN = re.compile(r"^https?://\S+")
_VALID_STATUSES: set[str] = {"draft", "review", "published", "archived"}

WEIGHTS: dict[str, float] = {
    "summary": 25,
    "depth": 25,
    "format": 20,
    "tags": 15,
    "buzzwords": 15,
}

GRADE_A: float = 80.0
GRADE_B: float = 60.0
BAR_WIDTH: int = 20

# ---------------------------------------------------------------------------
# File resolution (shared pattern with validate_json.py)
# ---------------------------------------------------------------------------


def resolve_files(args: list[str]) -> list[Path]:
    """Resolve CLI arguments to a list of existing JSON file paths.

    Args:
        args: Command-line arguments (file paths or glob patterns).

    Returns:
        Sorted list of unique Path objects for existing .json files.
    """
    filepaths: list[Path] = []
    seen: set[Path] = set()

    for arg in args:
        if _has_glob(arg):
            base = Path(arg)
            parent = base.parent
            pattern = base.name
            matches = sorted(parent.glob(pattern))
            if not matches:
                logger.warning("No files matched pattern: %s", arg)
            for m in matches:
                if m.is_file() and m not in seen:
                    filepaths.append(m)
                    seen.add(m)
        else:
            p = Path(arg)
            if p.is_file():
                if p not in seen:
                    filepaths.append(p)
                    seen.add(p)
            else:
                logger.warning("File not found: %s", p)

    return filepaths


def _has_glob(text: str) -> bool:
    """Check whether a string contains glob wildcard characters."""
    return "*" in text or "?" in text or "[" in text


# ---------------------------------------------------------------------------
# Visual helpers
# ---------------------------------------------------------------------------


def _bar(score: float, max_score: float, width: int = BAR_WIDTH) -> str:
    """Render a colored ASCII progress bar.

    Filled portion uses green/yellow/red based on ratio; empty portion is dimmed.

    Args:
        score: Current score value.
        max_score: Maximum possible score.
        width: Total character width of the bar.

    Returns:
        Colored string like ``[████████████░░░░░░░░]``.
    """
    ratio = score / max_score if max_score > 0 else 0.0
    filled = int(round(ratio * width))
    empty = width - filled

    fill_block = chr(9608) * filled
    empty_block = chr(9617) * empty

    color_key = _ratio_color(ratio)
    return (
        f"[{_color(color_key, fill_block)}"
        f"{_color('dim', empty_block)}]"
    )


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def _score_summary(summary: str) -> DimensionScore:
    """Score summary quality (max 25 points).

    Base score by length: >=50 chars → 20, >=20 chars → 12, else 5.
    Bonus up to +5 for unique tech keywords found in the text.

    Args:
        summary: The article summary string.

    Returns:
        DimensionScore with computed value.
    """
    length = len(summary)

    if length >= 50:
        base = 20.0
        detail = f"len={length} full"
    elif length >= 20:
        base = 12.0
        detail = f"len={length} basic"
    else:
        base = 5.0
        detail = f"len={length} short"

    found = {kw for kw in _TECH_KEYWORDS if kw in summary}
    bonus = min(len(found), 5)
    total = min(base + bonus, 25.0)

    if bonus:
        detail += f" +{bonus}kw"

    return DimensionScore(name="摘要质量", score=round(total, 1), max_score=25, details=detail)


def _score_depth(data: dict[str, Any]) -> DimensionScore:
    """Score technical depth from relevance_score (max 25 points).

    Reads ``score`` (top-level) or ``ai_analysis.relevance_score``.
    Maps 1-10 linearly to 0-25.

    Args:
        data: The parsed article JSON dict.

    Returns:
        DimensionScore with computed value.
    """
    raw = data.get("score")
    if raw is None:
        ai = data.get("ai_analysis")
        if isinstance(ai, dict):
            raw = ai.get("relevance_score")

    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        clamped = max(1, min(10, int(raw)))
        mapped = round((clamped - 1) / 9 * 25, 1)
        return DimensionScore(
            name="技术深度",
            score=mapped,
            max_score=25,
            details=f"score={clamped}→{mapped}",
        )

    return DimensionScore(name="技术深度", score=0.0, max_score=25, details="no score field")


def _score_format(data: dict[str, Any]) -> DimensionScore:
    """Score format compliance (max 20 points).

    Five items at 4 points each: id, title, source_url, status, collected_at.

    Args:
        data: The parsed article JSON dict.

    Returns:
        DimensionScore with computed value.
    """
    points = 0
    parts: list[str] = []

    if isinstance(data.get("id"), str) and _ID_PATTERN.match(data["id"]):
        points += 4
        parts.append("id✓")
    else:
        parts.append("id✗")

    if isinstance(data.get("title"), str) and data["title"].strip():
        points += 4
        parts.append("title✓")
    else:
        parts.append("title✗")

    url = data.get("source_url")
    if isinstance(url, str) and _URL_PATTERN.match(url):
        points += 4
        parts.append("url✓")
    else:
        parts.append("url✗")

    if data.get("status") in _VALID_STATUSES:
        points += 4
        parts.append("status✓")
    else:
        parts.append("status✗")

    ts = data.get("collected_at")
    if isinstance(ts, str) and ts.strip():
        points += 4
        parts.append("ts✓")
    else:
        parts.append("ts✗")

    return DimensionScore(
        name="格式规范",
        score=float(points),
        max_score=20,
        details=" ".join(parts),
    )


def _score_tags(tags: object) -> DimensionScore:
    """Score tag precision (max 15 points).

    Base by count: 1-3 → 10, 4-5 → 7, else → 3.
    Bonus up to +5 for tags matching the standard vocabulary.

    Args:
        tags: The ``tags`` field value from the article.

    Returns:
        DimensionScore with computed value.
    """
    if not isinstance(tags, list):
        return DimensionScore(name="标签精度", score=0.0, max_score=15, details="not a list")

    count = len(tags)
    if 1 <= count <= 3:
        base = 10.0
    elif 4 <= count <= 5:
        base = 7.0
    else:
        base = 3.0

    valid = sum(1 for t in tags if isinstance(t, str) and t in _STANDARD_TAGS)
    bonus = min(valid, 5)
    total = min(base + bonus, 15.0)

    return DimensionScore(
        name="标签精度",
        score=round(total, 1),
        max_score=15,
        details=f"{count}t/{valid}v",
    )


def _score_buzzwords(data: dict[str, Any]) -> DimensionScore:
    """Score buzzword avoidance (max 15 points).

    Start at 15; deduct 3 points per buzzword found in summary + title.
    Checks both Chinese and English blacklists.

    Args:
        data: The parsed article JSON dict.

    Returns:
        DimensionScore with computed value.
    """
    text = ""
    if isinstance(data.get("summary"), str):
        text += data["summary"]
    if isinstance(data.get("title"), str):
        text += " " + data["title"]

    cn = [w for w in _CN_BUZZWORDS if w in text]
    en = [w for w in _EN_BUZZWORDS if w.lower() in text.lower()]

    deductions = (len(cn) + len(en)) * 3
    score = max(0.0, 15.0 - deductions)
    all_found = cn + en

    detail = "clean" if not all_found else f"detected: {', '.join(all_found)}"

    return DimensionScore(
        name="空洞词检测",
        score=score,
        max_score=15,
        details=detail,
    )


# ---------------------------------------------------------------------------
# Evaluation entry point
# ---------------------------------------------------------------------------


def evaluate_article(filepath: Path) -> QualityReport | None:
    """Parse and score a single JSON article file.

    Args:
        filepath: Path to the article JSON file.

    Returns:
        QualityReport if the file is a valid JSON object, None otherwise.
    """
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict):
        return None

    dims = [
        _score_summary(data.get("summary", "")),
        _score_depth(data),
        _score_format(data),
        _score_tags(data.get("tags", [])),
        _score_buzzwords(data),
    ]

    total = round(sum(d.score for d in dims), 1)
    grade = "A" if total >= GRADE_A else ("B" if total >= GRADE_B else "C")

    return QualityReport(
        filepath=str(filepath),
        total_score=total,
        dimensions=dims,
        grade=grade,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse CLI args, evaluate articles, display report, set exit code."""
    global _USE_COLOR

    args = sys.argv[1:]

    force_color = "--color" in args
    if "--no-color" in args or "--color" in args:
        args = [a for a in args if a not in ("--no-color", "--color")]

    _USE_COLOR = force_color or (_USE_COLOR and _detect_color())

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args:
        logger.error("Usage: python hooks/check_quality.py <json_file> [json_file2 ...]")
        sys.exit(2)

    filepaths = resolve_files(args)

    if not filepaths:
        logger.error("No files to evaluate")
        sys.exit(2)

    reports: list[QualityReport] = []
    skipped: int = 0

    for fp in filepaths:
        report = evaluate_article(fp)
        if report is None:
            skipped += 1
            logger.warning("SKIP: %s (not a valid article JSON)", fp.name)
        else:
            reports.append(report)

    has_c = False

    for i, r in enumerate(reports):
        if i > 0:
            logger.info("")
        logger.info("%s", _color("cyan", r.filepath))
        logger.info(
            "  %s  %5.1f/100  %s",
            _bar(r.total_score, 100),
            r.total_score,
            _color(_grade_color(r.grade), f"Grade: {r.grade}"),
        )
        for d in r.dimensions:
            logger.info(
                "  %s: %s  %4.1f/%-4.0f  %s",
                d.name,
                _bar(d.score, d.max_score),
                d.score,
                d.max_score,
                d.details,
            )
        if r.grade == "C":
            has_c = True

    total = len(reports)
    a_cnt = sum(1 for r in reports if r.grade == "A")
    b_cnt = sum(1 for r in reports if r.grade == "B")
    c_cnt = sum(1 for r in reports if r.grade == "C")
    avg = round(sum(r.total_score for r in reports) / total, 1) if total > 0 else 0.0

    logger.info("")
    logger.info("=" * 50)
    logger.info(_color("bold", "Quality Check Summary"))
    logger.info("  Evaluated: %d", total)
    logger.info("  %s:  %d", _color("green", f"A (>={int(GRADE_A)}) "), a_cnt)
    logger.info("  %s:  %d", _color("yellow", f"B (>={int(GRADE_B)}) "), b_cnt)
    logger.info("  %s:  %d", _color("red", f"C (<{int(GRADE_B)})  "), c_cnt)
    logger.info("  Average:   %s", _color("bold", f"{avg:.1f}"))
    if skipped:
        logger.info("  Skipped:   %d", skipped)

    sys.exit(1 if has_c else 0)


if __name__ == "__main__":
    main()
