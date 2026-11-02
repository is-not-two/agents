# Agent 评测与真实效果的边界

运行：`.venv/Scripts/python.exe scripts/agent_eval.py --report output/eval/agent-contract.json`。
CI / Linux 使用相应 Python 解释器，同一 CLI 不依赖数据库、Docker、模型密钥或网络。

## 当前验证了什么

30 条版本化 fixture 调用实际 `AgentRuntime.start/_drive/confirm`，只有模型、工具传输和存储边界采用隔离的确定性适配器。覆盖正常答复、只读工具、未授权工具、错误 JSON、写前确认、拒绝/批准、空回答、模型失败、重复调用 ID、预算、异常工具和超大结果。

报告绑定任务集、运行时代码与评测适配器 SHA256；输出每条断言、实际状态、实际执行工具列表、调用次数、耗时。禁止空评测集、重复 ID、未知断言/权限及无效预算。故意改错预期应使门禁失败。

`release_gate.py --checks quick/full` 纳入此工程契约门禁。真实的 CI 是否已运行仍须查看相应远端流水线，不能因本地通过而声称远端发布成功。

## 当前没有验证什么

这些是工程契约，不是实际模型理解、摘要、检索或 JD 分析的质量分数。报告固定 `quality_verified=false`，`model=mock`，用量与费用标 `unknown`；不把模拟调用时间称为生产 p95，也不把 fixture 成功数当成用户任务成功率。

真实模型评测待有明确授权的模型连接与业务任务后，使用同一任务/提示词版本独立出报告，保留原始证据、人工修改量、耗时与实际 usage。缺密钥时不得绕过或伪造此验收。后续求职/学习功能须扩充业务 golden set，不能仅复用本批工具契约充数。
