---
name: tech-summary
description: 对 GitHub Trending 采集的 AI 技术项目进行深度分析，逐条生成摘要、技术亮点、评分与标签建议，并识别整体趋势。当需要对采集的技术内容进行深度分析总结时使用此技能。
allowed-tools: Read, Grep, Glob, WebFetch
---

# 技术深度分析技能

## 使用场景

- 读取 `knowledge/raw/` 中 github-trending 技能产出的采集数据
- 逐条深度分析每条技术项目，产出评分与技术亮点
- 发现本期项目的共同主题和新概念趋势
- 为"AI 知识库 v3"的整理 Agent 提供分析后的结构化数据

## 执行步骤

### 步骤 1：读取最新采集文件

使用 `Glob` 查找 `knowledge/raw/github-trending-*.json` 中最新的文件，`Read` 读取全部条目。
若未找到，输出提示并结束。

### 步骤 2：逐条深度分析

对 `items[]` 中的每条项目，使用 `WebFetch` 访问仓库页获取 README/描述补充信息后，逐项完成：

| 分析项 | 要求 |
|--------|------|
| **摘要** (`summary`) | ≤ **50 字**中文，一句话说清核心价值，不做展开 |
| **技术亮点** (`tech_highlights`) | **2-3 条**，用具体事实说话（如"已获 12k Star，周增 1.5k"、"支持 20+ LLM 模型接入"），禁止空泛描述 |
| **评分** (`score`) | 1-10 分整数，必须附理由，见下方评分标准 |
| **评分理由** (`score_reason`) | 1-2 句中文，基于项目成熟度、影响力、创新性给出明确理由 |
| **标签建议** (`tags`) | 2-5 个中文技术标签，如 `Agent框架`、`RAG管道`、`多模态`、`本地部署` |

### 步骤 3：趋势发现

综合分析全部条目后，提炼以下趋势信息：

| 趋势项 | 说明 |
|--------|------|
| **共同主题** (`common_themes`) | 本期多条项目涉及的相同技术方向，至少 2 条 |
| **新概念** (`new_concepts`) | 值得关注的新技术概念或范式，如无则 `[]` |
| **趋势概述** (`trend_summary`) | 1-3 句中文概括本期整体技术趋势 |

### 步骤 4：输出分析结果 JSON

写入 `knowledge/articles/tech-summary-YYYY-MM-DD.json`（日期为执行当天北京时间）。
写入前确保 `knowledge/articles/` 目录存在。

## 评分标准

| 分数 | 含义 | 判定依据 |
|------|------|----------|
| 9-10 | 改变格局 | 重大范式突破、行业级影响力、已大规模采用 |
| 7-8 | 直接有帮助 | 成熟实用、可直接用于项目、社区活跃 |
| 5-6 | 值得了解 | 有创新但早期、小众但设计优秀、值得追踪 |
| 1-4 | 可略过 | 信息量低、同质化严重、无明显差异化 |

> **强制约束**：15 个项目中 **9-10 分不超过 2 个**，整体分布需合理。

## 输出格式

```json
{
  "source": "github_trending",
  "skill": "tech-summary",
  "analyzed_at": "2026-05-03T14:30:00+08:00",
  "input_file": "github-trending-2026-05-03.json",
  "trends": {
    "common_themes": ["多Agent协作", "本地化AI部署"],
    "new_concepts": ["Graph RAG", "MCP协议"],
    "trend_summary": "本期以多Agent协作与本地化AI部署为主流方向，Graph RAG作为新兴范式值得持续关注。"
  },
  "items": [
    {
      "name": "crewAI/crewAI",
      "url": "https://github.com/crewAI/crewAI",
      "summary": "多Agent协作框架，编排AI团队完成复杂任务。",
      "score": 8,
      "score_reason": "已被多家企业采用，文档完善，生态整合度较高",
      "tech_highlights": [
        "已获 18k+ Star，周增 1.2k Star",
        "支持角色分工与多 Agent 动态编排",
        "与 LangChain、LlamaIndex 生态深度集成"
      ],
      "tags": ["Agent框架", "多Agent协作", "LLM编排"]
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | `str` | 是 | 固定值 `"github_trending"` |
| `skill` | `str` | 是 | 固定值 `"tech-summary"` |
| `analyzed_at` | `str` | 是 | 分析时间 ISO 8601（东八区） |
| `input_file` | `str` | 是 | 本次分析的源文件名 |
| `trends.common_themes` | `list[str]` | 是 | 本期共同技术主题，≥ 2 条 |
| `trends.new_concepts` | `list[str]` | 是 | 新概念/范式，无则 `[]` |
| `trends.trend_summary` | `str` | 是 | 趋势概述，1-3 句中文 |
| `items[].name` | `str` | 是 | 项目名，沿用原始数据 |
| `items[].url` | `str` | 是 | 仓库链接，沿用原始数据 |
| `items[].summary` | `str` | 是 | 中文摘要，≤ 50 字 |
| `items[].score` | `int` | 是 | 1-10 评分，整数 |
| `items[].score_reason` | `str` | 是 | 评分理由，1-2 句 |
| `items[].tech_highlights` | `list[str]` | 是 | 2-3 条技术亮点，每条用具体事实支撑 |
| `items[].tags` | `list[str]` | 是 | 2-5 个中文技术标签 |

## 注意事项

1. **评分严格性**：9-10 分不超过 15 个项目的 15%，即最多 **2 个**
2. **亮点可验证**：每条技术亮点必须有可追溯的事实依据（Star 数、技术特性、集成关系），禁止"功能强大""性能优异"等空话
3. **摘要长度**：严格 ≤ 50 字，超过必须压缩精简
4. **趋势客观**：趋势发现必须从本批次数据中归纳，不引入外部信息
5. **WebFetch 访问**：分析每条前用 WebFetch 访问仓库主页获取补充信息，确保分析准确
6. **请求间隔**：WebFetch 访问 GitHub 页面至少间隔 **2 秒**，避免触发限流
7. **允许工具**：本技能仅可使用 Read、Grep、Glob、WebFetch，不得调用 Bash 或 Edit
