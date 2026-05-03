---
name: github-trending
description: 从 GitHub Search API 搜索 AI/LLM/Agent 领域热门开源项目，过滤去重后生成中文摘要并输出结构化 JSON。当需要采集 GitHub 热门仓库或 AI 领域技术动态时使用此技能。
allowed-tools: Read, Glob, WebFetch
---

# GitHub Trending 采集技能

## 使用场景

- 采集 GitHub 上 AI/LLM/Agent/ML/NLP/RAG 领域的 trending 开源项目
- 为"AI 知识库 v3"项目的分析 Agent 提供原始数据输入

## 执行步骤

### 步骤 1：搜索热门仓库（GitHub API）

使用 WebFetch 调用 GitHub Search API，按 stars 降序搜索 AI 相关仓库：

```
https://api.github.com/search/repositories?q=ai+OR+llm+OR+agent+OR+machine+learning+OR+deep+learning+OR+nlp+OR+rag&sort=stars&order=desc&per_page=50
```

> **请求要求**：设置 `timeout=30`。建议设置 `Accept: application/vnd.github.v3+json` 请求头。
> 未认证请求限制 60 次/小时，触发限流后等待 `Retry-After` 时间再重试，最多重试 3 次（指数退避 1s → 4s → 16s）。

### 步骤 2：提取信息

从 API 响应 `items[]` 中为每条仓库提取以下字段：

| 字段 | API 字段 | 说明 |
|------|----------|------|
| `name` | `full_name` | `owner/repo` 格式 |
| `url` | `html_url` | 仓库 GitHub 链接 |
| `description` | — | 暂存原始描述，步骤 5 替换为中文摘要 |
| `language` | `language` | 主编程语言，无则为空字符串 `""` |
| `topics` | `topics` | GitHub 话题标签列表 |

### 步骤 3：过滤

- **纳入**：与 AI/LLM/Agent/ML/深度学习/NLP/RAG/Transformer/多模态/Embedding/向量检索/大模型 直接相关的项目
- **排除**（必须剔除）：
  - `awesome-*` / `Awesome-*` 列表合集
  - 纯教程/课程/面试题/文档类仓库（无实际代码实现，如 `awesome-llm`、`llm-course`）
  - 与 AI 无关的通用工具、前端 UI 库、DevOps 基础设施等

### 步骤 4：去重

基于 `name`（`owner/repo`）去重。若同一仓库出现多次，仅保留第一条。

### 步骤 5：撰写中文摘要

将 `description` 字段替换为中文摘要，公式：

> **项目名 + 做什么 + 为什么值得关注**

- 摘要长度：1-3 句中文，50-100 字
- 必须基于原始 `description` 和 `topics` 信息，不编造内容
- 示例：`crewAI/crewAI — 多 Agent 协作框架，支持角色分工与任务编排，LangChain 生态中增长最快的 Agent 项目之一。`

### 步骤 6：排序取 Top 15

按 `stargazers_count`（总 Star 数）降序排列，取前 **15** 条。

### 步骤 7：输出 JSON

写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`（日期为执行当天北京时间，如 `2026-05-03`）。
写入前确保 `knowledge/raw/` 目录存在，不存在则创建。

## 输出格式

```json
{
  "source": "github_trending",
  "skill": "github-trending",
  "collected_at": "2026-05-03T14:30:00+08:00",
  "items": [
    {
      "name": "crewAI/crewAI",
      "url": "https://github.com/crewAI/crewAI",
      "description": "crewAI/crewAI — 多 Agent 协作框架，支持角色分工与任务编排，LangChain 生态中增长最快的 Agent 项目之一。",
      "language": "Python",
      "topics": ["ai", "agents", "llm", "multi-agent", "langchain"]
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | `str` | 是 | 固定值 `"github_trending"` |
| `skill` | `str` | 是 | 固定值 `"github-trending"` |
| `collected_at` | `str` | 是 | 采集时间 ISO 8601（东八区） |
| `items[].name` | `str` | 是 | `owner/repo` 格式 |
| `items[].url` | `str` | 是 | 仓库 GitHub 链接 |
| `items[].description` | `str` | 是 | 中文摘要（1-3 句） |
| `items[].language` | `str` | 是 | 主编程语言，无则为 `""` |
| `items[].topics` | `list[str]` | 是 | GitHub 话题标签，无则为 `[]` |

## 注意事项

1. **摘要真实性**：中文摘要必须严格基于仓库真实信息，禁止凭空编造功能和亮点
2. **过滤优先级**：Awesome 列表和课程类仓库最容易漏网，检查时优先排查
3. **输出一致性**：文件名字段（`source`、`skill`）必须与规范完全一致，不得使用其他值
4. **请求失败**：单次请求失败需重试（最多 3 次），全部失败记录日志并返回空结果
5. **数量达标**：若过滤后不足 15 条，输出实际条数即可，不得凑数
6. **允许工具**：本技能仅可使用 Read、Glob、WebFetch，不得调用 Bash 或 Edit 工具
