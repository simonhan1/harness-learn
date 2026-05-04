# AI 知识库 v3 — AGENTS.md

> 本文件面向人类开发者与 AI Agent，是协作开发的最高准则。当指令与本文件冲突时，以本文件为准。

---

## 1. 项目概述

自动从 GitHub Trending 和 Hacker News 采集 AI/LLM/Agent 领域的技术动态，经 AI 分析去重、分类、摘要后结构化存储为 JSON，并通过 Telegram / 飞书 Bot 多渠道分发，构建一个"采集 → 分析 → 分发"全自动的 AI 知识库助手。

### 技术栈

| 层面 | 技术 |
|------|------|
| 语言 | Python 3.12 |
| 编排 | OpenCode + 国产大模型（DeepSeek / Qwen 等） |
| 存储 | JSON 文件（本地）+ 后续可扩展数据库 |
| 分发 | Telegram Bot API / 飞书自定义机器人 |

---

## 2. Agent 协作流程（最高优先级）

项目由三个 Agent 构成采集 → 分析 → 整理的流水线，各 Agent 通过 `knowledge/` 目录中的 JSON 文件进行数据交接。

| Agent | 职责 | 输入 | 输出 | 调用方式 |
|-------|------|------|------|----------|
| **采集** (`collector`) | 从 GitHub Trending / Hacker News 抓取 AI 相关内容，去噪、过滤非 AI 内容 | 用户指定数据源或执行全量采集 | `knowledge/raw/*.json` | 用户指令触发 |
| **分析** (`analyzer`) | 调用大模型对原始内容去重、分类、摘要、评分 | `knowledge/raw/*.json` | `knowledge/articles/*.json` | 用户指令触发 |
| **整理** (`curator`) | 过滤低质量条目、排序、触发多渠道分发 | `knowledge/articles/*.json` | 分发消息（Telegram / 飞书） | 用户指令触发 |

### 2.1 采集 Agent 行为规范

- 请求频率控制：对同一源至少间隔 **30 秒**
- 失败重试：单源最多重试 **3 次**，指数退避（1s → 4s → 16s）
- 全部源失败：写 ERROR 日志并优雅退出，不抛未捕获异常
- 输出写入 `knowledge/raw/`，文件名格式：`{source}_{YYYYMMDD_HHMMSS}.json`

### 2.2 分析 Agent 行为规范

- 输入为 `knowledge/raw/` 下最新的未处理文件
- 去重逻辑：基于 URL + 标题相似度（阈值 ≥ 0.85 视为重复）
- AI 调用失败：单条最多重试 **2 次**，仍失败标记 `status: "analysis_failed"`
- 分析结果中 `status` 默认必须为 `"draft"`，不得直接设为 `"published"`

### 2.3 整理 Agent 行为规范

- 过滤规则：`relevance_score < 5` 的条目不推送（1-10 分制，与分析 Agent 评分标准一致）
- 排序：按 `relevance_score` 降序
- 推送失败：单渠道最多重试 **2 次**，失败记录 ERROR 日志
- 推送成功后将条目 `status` 更新为 `"published"`

### 2.4 文件命名与交接约定

各 Agent 通过 `knowledge/` 目录进行数据交接，文件命名和存放位置遵循以下统一规范：

```
knowledge/
├── raw/                                    # 采集 Agent 输出
│   └── {source}_{YYYYMMDD_HHMMSS}.json     # 每源一个文件，含 source + collected_at + items[]
├── articles/                               # 分析 → 整理阶段
│   ├── {YYYYMMDD}-{source}-analysis.json   # 分析 Agent 批量输出（中间产物）
│   └── {date}-{source}-{slug}.json         # 整理后的标准知识条目（单条一文件）
└── articles/.processed/                    # 已处理中间文件归档
```

| 阶段 | 输出者 | 文件位置 | 命名格式 | 接收者判定"待处理"方式 |
|------|--------|----------|----------|----------------------|
| 采集 → 分析 | 采集 Agent | `knowledge/raw/` | `{source}_{YYYYMMDD_HHMMSS}.json` | 按文件修改时间取最新 |
| 分析 → 整理 | 分析 Agent | `knowledge/articles/` | `{YYYYMMDD}-{source}-analysis.json` | 查找 `*-analysis.json`，按日期取最新 |
| 整理 → 分发 | 整理 Agent | `knowledge/articles/` | `{date}-{source}-{slug}.json` | 分发层读取 `status == "draft"` 条目 |

**命名规范速查：**

| 用途 | 格式 | 示例 |
|------|------|------|
| 原始采集数据 | `{source}_{YYYYMMDD_HHMMSS}.json` | `github_trending_20260501_120000.json` |
| 分析批量结果 | `{YYYYMMDD}-{source}-analysis.json` | `20260501-github-analysis.json` |
| 标准知识条目 | `{date}-{source}-{slug}.json` | `20260501-github-openai-cookbook.json` |

**交接规则：**
- 采集 Agent 仅写入 `knowledge/raw/`，不得写入 `knowledge/articles/`
- 分析 Agent 产出中间文件写入 `knowledge/articles/`（`*-analysis.json`）
- 整理 Agent 处理结束后，须将 `*-analysis.json` 中间文件移至 `.processed/` 归档，避免后续重复处理
- 同一批采集数据在一次工作流中只被处理一次

---

## 3. 编码规范（第二优先级）

### 3.1 风格

- 遵循 **PEP 8** 风格指南
- 命名：变量/函数/模块用 **`snake_case`**，类名用 **`PascalCase`**，常量用 **`UPPER_SNAKE_CASE`**
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

### 3.2 日志与输出

- **禁止使用裸 `print()`** — 必须通过 `logging` 模块输出
- 各模块独立 logger：`logger = logging.getLogger(__name__)`
- 日志级别按场景选用：`DEBUG` / `INFO` / `WARNING` / `ERROR`
- AI 调用、采集、推送等关键环节必须输出 **INFO** 级别日志

### 3.3 类型注解

- 所有函数参数和返回值必须加类型标注（Python 3.12 语法）

### 3.4 文件规模

- 单文件不超过 **500 行**，超过则拆分模块

---

## 4. 项目结构

```
ai-knowledge-base-v3/
├── AGENTS.md
├── pyproject.toml
├── .agents/                  # Sub-agent 定义 + Skill 定义
├── src/
│   ├── collector/            # 采集层（GitHub Trending / Hacker News）
│   ├── analyzer/             # AI 分析层（去重、分类、摘要、评分）
│   ├── storage/              # 存储层（JSON 读写 + 后续数据库抽象）
│   ├── distributor/          # 分发层（Telegram Bot / 飞书 Webhook）
│   └── config.py             # 统一配置入口
├── knowledge/
│   ├── raw/                  # 原始抓取内容（JSON）
│   └── articles/             # AI 分析后的结构化知识条目（JSON）
├── tests/
├── .env.example              # 环境变量模板（不含真实值）
└── .gitignore
```

---

## 5. 知识条目 JSON 格式

每条知识条目使用以下结构（存放于 `knowledge/articles/`）：

```json
{
  "id": "kb-20260428-001",
  "title": "OpenAI 发布 GPT-5 重大更新",
  "source": "hacker_news",
  "source_url": "https://news.ycombinator.com/item?id=xxxxx",
  "summary": "AI 生成的 1-3 句中文摘要",
  "tags": ["OpenAI", "GPT-5", "LLM"],
  "category": "model_release",
  "status": "draft",
  "collected_at": "2026-04-28T10:30:00+08:00",
  "published_at": null,
  "ai_analysis": {
    "relevance_score": 9,
    "key_points": ["多模态能力提升", "推理成本降低 50%"],
    "sentiment": "positive"
  }
}
```

| 字段 | 类型 | 说明 | 必填 |
|------|------|------|------|
| `id` | `str` | 唯一标识，格式 `kb-YYYYMMDD-NNN` | 是 |
| `title` | `str` | 文章/项目标题 | 是 |
| `source` | `str` | 来源：`github_trending` / `hacker_news` | 是 |
| `source_url` | `str` | 原文链接 | 是 |
| `summary` | `str` | AI 生成的中文摘要 | 是 |
| `tags` | `list[str]` | 标签列表 | 是 |
| `category` | `str` | 分类枚举：`model_release` / `agent_framework` / `tool` / `paper` / `opinion` | 是 |
| `status` | `str` | 状态：`draft` / `published` / `archived` / `analysis_failed` | 是 |
| `collected_at` | `str` | 采集时间（ISO 8601） | 是 |
| `published_at` | `str|null` | 原始发布时间，可能为空 | 否 |
| `ai_analysis` | `object|null` | AI 分析元信息（评分、要点、情感） | 否 |

### 原始采集条目格式（`knowledge/raw/`）

```json
{
  "source": "github_trending",
  "collected_at": "2026-04-28T10:30:00+08:00",
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "description": "repo description（英文原文，不翻译）",
      "stars": 1234,
      "language": "Python",
      "topics": ["ai", "llm", "agent"]
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | `str` | 是 | `owner/repo` 格式 |
| `url` | `str` | 是 | 仓库 GitHub 链接 |
| `description` | `str` | 是 | 原始英文描述，**采集阶段不生成中文摘要** |
| `stars` | `int` | 是 | 总 Star 数 |
| `language` | `str` | 是 | 主编程语言，无则为 `""` |
| `topics` | `list[str]` | 否 | GitHub 话题标签列表，无则为 `[]` |

---

## 6. 配置管理

- 敏感信息（API Key、Bot Token 等）→ `.env` 文件，通过 `python-dotenv` 加载
- `.env` 已加入 `.gitignore`，**绝对不得提交**
- 提供 `.env.example` 模板，列出所有需要的环境变量名和说明
- 非敏感配置（采集频率、分类标签等）→ YAML 配置文件

---

## 7. AI 调用规范

- AI 模型通过环境变量配置，代码中不硬编码模型名或 URL
- 所有 AI 调用必须有**重试机制** + **限流处理**
- 采集失败：重试 3 次 + 指数退避（1s → 4s → 16s），全部失败跳过该源并记录日志
- AI 分析失败：重试 2 次，仍失败标记 `status: "analysis_failed"`，不阻塞其他条目
- 推送失败：重试 2 次，失败记录 ERROR 日志

---

## 8. 日志规范

- 使用标准 `logging` 模块，**禁止 `print()`**
- 各模块独立 logger：`logger = logging.getLogger(__name__)`
- 关键环节（采集启动、AI 调用、推送结果）输出 INFO 日志
- 异常捕获后输出 ERROR 日志，包含完整 traceback

---

## 9. 红线（绝对禁止）

| # | 规则 | 说明 |
|---|------|------|
| 1 | **禁止硬编码凭据** | Token / API Key / Secret 必须通过环境变量或 `.env` 加载 |
| 2 | **禁止提交凭据文件** | `.env`、`credentials.json`、`*.key` 等已加入 `.gitignore`，绝对不得提交 |
| 3 | **禁止 `exec()` / `eval()`** | 杜绝任意代码执行风险 |
| 4 | **禁止无限流 HTTP 请求** | 所有外部请求必须设置间隔或退避策略，且必须设 timeout |
| 5 | **禁止 AI 内容直接发布** | AI 分析产生的条目 `status` 默认必须为 `"draft"`，审核后方可改为 `"published"` |
| 6 | **禁止跳过异常处理** | 每个 Agent 必须包 `try/except`，失败时写入 ERROR 日志并优雅退出 |
| 7 | **禁止 TODO/FIXME 进入 main 分支** | CI 检测命中即失败，feature 分支允许 |
| 8 | **AI Agent 禁止读取 `.env` 文件** | AI Agent 只能参考 `.env.example`，不得查看真实凭据 |
| 9 | **禁止在对话中暴露 `.env` 内容** | 与 AI 交互时不得粘贴或引用 `.env` 中的任何值 |
| 10 | **所有 HTTP 请求必须设 timeout** | `requests.get(url, timeout=30)` 等，禁止无超时请求 |

---

## 10. 验证方式

- CI 流水线运行 **lint 检查 + 单元测试**
- 单测覆盖率要求 **> 80%**
- 所有 Agent 的关键路径必须有对应测试用例

---

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/<feature>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

Defaults: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
