# AI 知识库 编码规范 V0.2

## 项目说明
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

## 边界 & 验收
- 单测覆盖率 > 80%

## 怎么验证
- CI 上跑 lint + 单测