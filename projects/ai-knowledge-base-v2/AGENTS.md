# AGENTS.md — AI 知识库 v2

> 本文件同时面向人类开发者与 AI agent。所有规范在 CI 上自动验证。

---

## 项目概述

自动从 GitHub Trending 和 Hacker News 采集 AI/LLM/Agent 领域技术动态，经 AI 分析去重、分类、摘要后结构化存储，并通过 Telegram / 飞书 Bot 分发。

### 技术栈

| 层 | 技术 |
|---|---|
| 语言 | Python 3.12 |
| 包管理 | uv (pyproject.toml) |
| 格式化 & Lint | ruff |
| 类型检查 | mypy |
| 测试 | pytest + pytest-cov |
| 存储 | SQLite |
| 配置 | .env (敏感) + YAML (非敏感) |
| 调度 | APScheduler + CLI 入口 |
| CI | GitHub Actions |

### 目录结构

```
ai-knowledge-base-v2/
├── src/
│   ├── collector/          # 采集层 (GitHub / HN)
│   ├── analyzer/           # AI 分析 + 去重
│   ├── storage/            # SQLite 读写
│   ├── distributor/        # Telegram / 飞书 Bot
│   └── config.py           # 统一配置入口
├── tests/
├── data/                   # SQLite 数据库 + JSON 存档
├── pyproject.toml
├── .env.example
├── .github/workflows/ci.yml
└── AGENTS.md
```

---

## 编码规范

### 格式化与 Lint

- 使用 **ruff** 统一处理格式化、lint、import 排序
- 遵循 PEP 8
- CI 命令：
  ```bash
  ruff check .
  ruff format --check .
  ```

### 类型检查

- 使用 **mypy**，严格模式
- CI 命令：`mypy src/`

### 文档规范

- 使用 **Google style** docstring
- 公开函数 = 不以 `_` 开头的函数
- 最少要求：summary line + Args + Returns
- 示例：
  ```python
  def fetch_trending(lang: str = "python") -> list[dict]:
      """采集 GitHub Trending 仓库列表.

      Args:
          lang: 编程语言过滤，默认 "python".

      Returns:
          仓库信息列表，每个元素包含 name, url, stars, description.
      """
  ```
- CI 用 ruff pydocstyle 规则（D 前缀）自动检查

### 魔法字符串

- 所有业务状态值、分类名、配置 key 必须定义为**模块级常量**或 **Enum** 类型
- 包含但不限于：频道名、API endpoint、采集源标识、内容分类标签
- 不包含：日志消息、标点符号、一次性临时字符串

### TODO 与 FIXME

- 格式：`# TODO: description here`
- 禁止 `TODO` 和 `FIXME` 提交到 main 分支
- feature 分支允许
- CI 用 `rg "TODO|FIXME" src/` 检测，命中即失败

---

## 测试与覆盖率

- 测试框架：pytest
- 覆盖率工具：pytest-cov
- CI 命令：
  ```bash
  pytest --cov=src --cov-report=term --cov-fail-under=80
  ```
- 类型要求：**整体行覆盖率 ≥ 80%，分支覆盖率 ≥ 70%**
- 豁免文件（自动排除）：`__init__.py`、`constants.py`、`types.py`、入口文件 (`main.py` 等)
- 不达标 CI 硬失败，禁止合并

---

## CI 流水线 (GitHub Actions)

完整 CI 步骤，按顺序执行：

```bash
uv sync --frozen

ruff check .
ruff format --check .

mypy src/

pytest --cov=src --cov-fail-under=80

# 禁止 TODO/FIXME 合并到 main
rg "TODO|FIXME" src/ && exit 1 || exit 0
```

---

## 配置管理

- 敏感信息（API Key, Bot Token）→ `.env`，使用 `python-dotenv` 加载
- `.env` 已加入 `.gitignore`
- 提供 `.env.example` 模板，列出所需变量名（不包含真实值）
- 非敏感配置（采集频率、分类名等）→ YAML 配置文件
- **AI agent 绝对不能读取或修改 `.env` 文件，只能参考 `.env.example`**

---

## AI 调用规范

- AI 模型通过环境变量配置，不硬编码
- 必须有**重试机制** + **限流处理**
- 采集失败：重试 3 次 + 指数退避，全失败跳过该源并记录日志
- AI 分析失败：重试 2 次，仍失败标记为 `analysis_failed`，不阻塞其他条目
- 推送失败：重试 + 失败日志

---

## 日志

- 使用标准 `logging` 模块
- 各模块独立 logger：`logger = logging.getLogger(__name__)`
- AI 调用、采集、推送等关键环节必须输出 INFO 级别日志
