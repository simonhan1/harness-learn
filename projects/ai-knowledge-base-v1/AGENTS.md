# AI Knowledge Base — AGENTS.md

## 项目概述

自动从 GitHub Trending 和 Hacker News 采集 AI/LLM/Agent 领域的技术动态，经 AI 分析去重、分类、摘要后结构化存储为 JSON，并通过 Telegram / 飞书 Bot 多渠道分发，构建一个"采集 → 分析 → 分发"全自动的 AI 知识库助手。

## 技术栈

| 层面 | 技术 |
|------|------|
| 语言 | Python 3.12 |
| 编排 | OpenCode + 国产大模型（DeepSeek / Qwen 等） |
| 工作流 | LangGraph（状态图驱动 Agent 协作） |
| 抓取 | OpenClaw（声明式采集框架） |
| 存储 | JSON 文件（本地）+ 后续可扩展数据库 |
| 分发 | Telegram Bot API / 飞书自定义机器人 |

## 编码规范

- 遵循 **PEP 8** 风格指南
- 命名使用 **`snake_case`**（变量、函数、模块、包）
- 类名使用 **`PascalCase`**
- 常量使用 **`UPPER_SNAKE_CASE`**
- Docstring 采用 **Google 风格**

```python
def fetch_trending(top_n: int = 30) -> list[dict]:
    """Fetch AI-related trending repos from GitHub.

    Args:
        top_n: Number of trending items to fetch.

    Returns:
        List of raw trending item dicts.

    Raises:
        ConnectionError: If GitHub API is unreachable.
    """
```

- **禁止使用裸 `print()`** — 必须通过 `logging` 模块输出（`import logging`），日志级别按场景选用：`DEBUG` / `INFO` / `WARNING` / `ERROR`
- 类型注解：所有函数参数和返回值必须加类型标注（Python 3.12 语法）
- 单文件不超过 500 行，超过则拆分模块

## 项目结构

```
ai-knowledge-base-v1/
├── AGENTS.md
├── .opencode/
│   ├── agents/          # Agent 定义（LangGraph 图配置）
│   ├── skills/          # Agent 技能模块（可复用技能包）
│   └── ...
├── knowledge/
│   ├── raw/             # 原始抓取内容（JSON）
│   └── articles/        # AI 分析后的结构化知识条目（JSON）
└── ...
```

## 知识条目 JSON 格式

每条知识条目使用以下结构（存放于 `knowledge/articles/`）：

```json
{
  "id": "kb-20260428-001",
  "title": "OpenAI 发布 GPT-5 重大更新",
  "source": "hacker_news",
  "source_url": "https://news.ycombinator.com/item?id=xxxxx",
  "summary": "OpenAI 发布了 GPT-5...（AI 生成的 1-3 句摘要）",
  "tags": ["OpenAI", "GPT-5", "LLM"],
  "category": "model_release",
  "status": "published",
  "collected_at": "2026-04-28T10:30:00+08:00",
  "published_at": "2026-04-28T08:00:00Z",
  "ai_analysis": {
    "relevance_score": 0.95,
    "key_points": ["多模态能力提升", "推理成本降低 50%"],
    "sentiment": "positive"
  }
}
```

| 字段 | 说明 | 必填 |
|------|------|------|
| `id` | 唯一标识，格式 `kb-YYYYMMDD-NNN` | 是 |
| `title` | 文章/项目标题 | 是 |
| `source` | 来源：`github_trending` / `hacker_news` | 是 |
| `source_url` | 原文链接 | 是 |
| `summary` | AI 生成的摘要 | 是 |
| `tags` | 标签列表 | 是 |
| `category` | 分类：`model_release` / `agent_framework` / `tool` / `paper` / `opinion` | 是 |
| `status` | 状态：`draft` / `published` / `archived` | 是 |
| `collected_at` | 采集时间（ISO 8601） | 是 |
| `published_at` | 原始发布时间 | 否 |
| `ai_analysis` | AI 分析元信息（评分、要点、情感） | 否 |

## AGENTS 角色概览

| Agent | 职责 | 输入 | 输出 | 使用 Skill |
|-------|------|------|------|------------|
| **采集** (`collector`) | 定时从 GitHub Trending / Hacker News 抓取 AI 相关内容 | 空（定时触发）或手动指定源 | `knowledge/raw/*.json` | `skills/scraper` |
| **分析** (`analyzer`) | 调用大模型对原始内容去重、分类、摘要、评分 | `knowledge/raw/*.json` | `knowledge/articles/*.json` | `skills/llm_analysis` |
| **整理** (`curator`) | 过滤低质量条目、排序、触发多渠道分发 | `knowledge/articles/*.json` | 分发消息（Telegram / 飞书） | `skills/publisher` |

三个 Agent 通过 LangGraph 编排为有向无环图（DAG），采集完成后自动触发分析，分析完成自动触发整理。

## 红线（绝对禁止）

1. **禁止在代码中硬编码 Token / API Key / Secret** — 必须通过环境变量或 `.env` 文件加载
2. **禁止将任何凭据文件提交到 Git**（包括 `.env`、`credentials.json`、`*.key`、`config.json` 含敏感信息）
3. **禁止使用 `exec()` / `eval()`** — 杜绝任意代码执行风险
4. **禁止未经限流（rate-limit）的 HTTP 请求** — 所有外部请求必须设置间隔或退避策略
5. **禁止 AI 分析产生的内容不经人工审核标记直接对外发布**（`status` 默认必须为 `draft`，审核后方可改为 `published`）
6. **禁止跳过异常处理直接崩溃** — 每个 Agent 必须包 `try/except`，失败时写入错误日志并优雅退出
