## Why

当前 LLM 分析层缺乏智能 retry 机制：无法区分可重试错误（网络超时、5xx）和不可重试错误（4xx 凭据错误），导致时间浪费。同时，批量分析时单条失败会中断整个流程，造成已消耗 token 浪费。需要建立可重试错误的清晰定义、支持批量容错继续、以及统一的 retry 配置策略。

## What Changes

- **model_client.py**: 增加 HTTP 状态码检查，仅对 5xx、超时、网络错误等可重试错误进行 retry，对 4xx 等不可重试错误立即失败
- **pipeline.py `_analyze_single()`**: 捕获 JSONDecodeError 但不重试，标记为 `analysis_failed` 并继续处理后续项
- **pipeline.py `analyze()` 函数**: 确保单条失败不中断批量处理，所有项都被分析（成功或失败标记）
- **AGENTS.md**: 补充 retry 配置规范（固定 3 次、指数退避基数 1s）
- **配置一致性**: 采集层和分析层 retry 次数对齐为 3，超时统一为 60s

## Capabilities

### New Capabilities

- `intelligent-http-retry`: 根据 HTTP 状态码智能判断是否重试，避免盲目重试不可恢复的错误
- `batch-failure-tolerance`: 批量分析时支持单条失败不中断流程，后续项继续处理

### Modified Capabilities

- `llm-analysis`: 强化分析层容错机制，失败的单条项不中断整批处理，改进错误分类

## Impact

- **model_client.py**: 新增 `_is_retryable_error()` 辅助函数，修改 `chat_with_retry()` 逻辑
- **pipeline.py**: 修改 `_analyze_single()` 和 `analyze()` 的错误处理逻辑
- **AGENTS.md**: 补充 retry 配置部分（新增第 7.1 节）
- **无 breaking changes**: 现有 API 签名保持不变，retry 策略改进是内部优化
- **依赖**: 无新增依赖
