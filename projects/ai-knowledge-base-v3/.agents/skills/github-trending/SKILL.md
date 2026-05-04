---
name: github-trending
description: 从 GitHub Search API 搜索 AI/LLM/Agent 领域热门开源项目，过滤去重后输出结构化原始数据 JSON。当需要采集 GitHub 热门仓库或 AI 领域技术动态时使用此技能。
allowed-tools: Read, Write, Glob, Bash
---

# GitHub Trending 采集技能

## 使用场景

- 采集 GitHub 上 AI/LLM/Agent/ML/NLP/RAG 领域的 trending 开源项目
- 为"AI 知识库 v3"项目的分析 Agent 提供原始数据输入

## 执行步骤

### 步骤 1：搜索热门仓库（GitHub API）

使用 `bash + curl` 调用 GitHub Search API，按 stars 降序搜索 AI 相关仓库：

```bash
curl -s -H "Accept: application/vnd.github.v3+json" -H "User-Agent: ai-knowledge-base-v3" \
  "https://api.github.com/search/repositories?q=ai+OR+llm+OR+agent+OR+nlp+OR+rag&sort=stars&order=desc&per_page=50"
```

> **为什么不用 WebFetch**：GitHub API 强制要求 `User-Agent` 请求头，WebFetch 无法自定义请求头，会返回 422 错误。必须使用 curl。
>
> **查询限制**：GitHub Search API 的 `q` 参数最多 **5 个** AND/OR/NOT 操作符。超出会返回 `422 Validation Failed`（`More than five AND / OR / NOT operators were used`）。当前查询包含 4 个 OR，符合限制。
>
> **请求要求**：设置 `timeout=30`。未认证请求限制 60 次/小时，触发限流后等待 `Retry-After` 时间再重试，最多重试 3 次（指数退避 1s → 4s → 16s）。

API 响应为 JSON，输出到文件后由步骤 2 解析。若需保存原始响应到临时文件，使用 `--output <tempfile>` 参数。

### 步骤 2：提取信息

从 API 响应 `items[]` 中为每条仓库提取以下字段：

| 字段 | API 字段 | 说明 |
|------|----------|------|
| `name` | `full_name` | `owner/repo` 格式 |
| `url` | `html_url` | 仓库 GitHub 链接 |
| `description` | `description` | 原始英文描述（不翻译，不生成中文摘要） |
| `stars` | `stargazers_count` | 总 Star 数 |
| `language` | `language` | 主编程语言，无则为空字符串 `""` |
| `topics` | `topics` | GitHub 话题标签列表，无则为 `[]` |

### 步骤 3：过滤

- **纳入**：与 AI/LLM/Agent/ML/深度学习/NLP/RAG/Transformer/多模态/Embedding/向量检索/大模型 直接相关的项目
- **排除**（必须剔除）：
  - `awesome-*` / `Awesome-*` 列表合集
  - 纯教程/课程/面试题/文档类仓库（无实际代码实现，如 `awesome-llm`、`llm-course`）
  - 与 AI 无关的通用工具、前端 UI 库、DevOps 基础设施等

### 步骤 4：去重

基于 `name`（`owner/repo`）去重。若同一仓库出现多次，仅保留第一条。

### 步骤 5：排序取 Top 15

按 `stargazers_count`（总 Star 数）降序排列，取前 **15** 条。

### 步骤 6：输出 JSON

写入 `knowledge/raw/`，文件名格式 `{source}_{YYYYMMDD_HHMMSS}.json`（如 `github_trending_20260503_130258.json`）。
写入前确保 `knowledge/raw/` 目录存在，不存在则创建。

## 输出格式

```json
{
  "source": "github_trending",
  "collected_at": "2026-05-03T14:30:00+08:00",
  "items": [
    {
      "name": "crewAI/crewAI",
      "url": "https://github.com/crewAI/crewAI",
      "description": "Framework for orchestrating role-playing autonomous AI agents",
      "stars": 18500,
      "language": "Python",
      "topics": ["ai", "agents", "llm", "multi-agent", "langchain"]
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | `str` | 是 | 固定值 `"github_trending"` |
| `collected_at` | `str` | 是 | 采集时间 ISO 8601（东八区） |
| `items[].name` | `str` | 是 | `owner/repo` 格式 |
| `items[].url` | `str` | 是 | 仓库 GitHub 链接 |
| `items[].description` | `str` | 是 | 原始英文描述，不翻译 |
| `items[].stars` | `int` | 是 | 总 Star 数 |
| `items[].language` | `str` | 是 | 主编程语言，无则为 `""` |
| `items[].topics` | `list[str]` | 否 | GitHub 话题标签，无则为 `[]` |

## 注意事项

1. **描述真实性**：`description` 保留原始英文文本，不翻译、不编造，中文摘要由分析 Agent 在后续阶段生成
2. **过滤优先级**：Awesome 列表和课程类仓库最容易漏网，检查时优先排查
3. **输出一致性**：文件名和字段必须与规范完全一致，不得使用其他值
4. **请求失败**：单次请求失败需重试（最多 3 次），全部失败记录日志并返回空结果
5. **数量达标**：若过滤后不足 15 条，输出实际条数即可，不得凑数
6. **处理流程**：curl 获取原始 JSON → Python 脚本解析/过滤/去重/排序 → Write 输出最终文件。Python 脚本中须用 `encoding='utf-8'` 读写文件，避免 Windows GBK 编码问题。

## 常见错误与修复

| 错误 | 现象 | 原因 | 修复 |
|------|------|------|------|
| `422 Validation Failed` — `More than five AND / OR / NOT operators` | curl 返回 422 | 查询中 OR 操作符超过 5 个 | 精简搜索词，控制在 5 个操作符以内 |
| `422 Validation Failed` — 无具体说明 | WebFetch 返回 422 | 缺少 `User-Agent` 请求头 | 改用 `bash + curl`，添加 `-H "User-Agent: ..."` 头 |
| `UnicodeDecodeError: 'gbk' codec` | Python 读取文件报错 | Windows 默认 GBK 编码 | 读写文件时显式指定 `encoding='utf-8'` |
| `UnicodeEncodeError: 'gbk' codec` | 含 emoji 的描述无法打印 | stdout 使用 GBK 编码 | 添加 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')` |
