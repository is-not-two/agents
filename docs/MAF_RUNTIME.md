# 多 Agent 协作运行时（Microsoft Agent Framework）

## 为什么引入

自研 DAG（`agent/graph_runner.py`）擅长**可复用的静态流程**：能存、能审、能改、能复跑。
它不擅长两件事：

1. **Agent 之间真通信**。现有 `agent/collaboration.py` 是「主管提计划 → 顺序派活」，
   Worker 各干各的，看不到彼此中间结论。
2. **运行时自适应规划**。给一句话目标，边做边改计划，而不是一次生成静态图。

这两件事 MAF 现成：`GroupChatBuilder`（群聊，轮流发言）、`HandoffBuilder`（交接）、
`MagenticBuilder`（规划 → 派活 → 进度台账 → 重规划）、`ConcurrentBuilder`（并发 + 聚合）。

## 边界：只在适配层出现

```
资产层  记录库 + JSON DAG + 编辑器 + 审批政策      ← 保留自研，不动
  ↓
协作层  maf_runtime.py（本文件）                  ← MAF 全部收敛在这里
  ↓
能力层  CapabilityService 工具 + code_workspace   ← 保留自研，包成 MAF 工具
```

全仓库只有 `platform/maf_runtime.py` 出现 `import agent_framework`。
业务代码只调 `run_team()`，框架升级或替换时改动收敛在一个文件。

## 安装（服务器必须 Python 3.11+）

```bash
pip install -e ".[maf]"
```

`agent-framework-core 1.25.0` 的元数据写死 `Requires-Python >=3.11`，3.10 装不进去。
未安装时导入本模块不会报错，调用时才抛 `DomainError` 并附带安装命令——
这样 3.10 的部署仍能启动，只是团队编排不可用。

## 用法

```python
from rag_tech_retriever.platform import maf_runtime as maf

client = maf.ProviderChatClient(limits, model, config, specs)   # 复用 post_chat
tools = maf.build_tools(specs, dispatch)                        # 注册表 schema 直通
coder = maf.build_agent(client, profile, tools)
reviewer = maf.build_agent(client, profile)
manager = maf.build_agent(client, {"key": "manager", "system_prompt": "..."})

result = await maf.run_team("给这个仓库加上重试", [coder, reviewer], manager,
                            mode="group_chat", max_rounds=6)
# result: {"mode", "turns": [...], "final": "...", "speakers": [...]}
```

## 四个接口对接点（实测）

| 我们这边 | MAF 那边 | 说明 |
|---|---|---|
| `common.provider.post_chat` | `BaseChatClient._inner_get_response` | 唯一抽象方法；返回 `ResponseStream`（工具层只吃流） |
| Agent 指令 | `options["instructions"]` | **不在 messages 里**，适配层自己补成 system 消息，否则指令丢失 |
| 能力注册表 JSON Schema | `FunctionTool(input_model=...)` | schema 与只读标记来自注册表，Agent 无法自己放权；写工具挂审批 |
| 工具结果 | `role=tool` 独立消息 | 塞进 assistant 会让模型重复调用 |

## 事件映射

`workflow.run(task, stream=True)` 的 `WorkflowEvent`：

- `executor_id` = 谁在说话（不是 `author_name`，后者常为空）
- `data` 可能是 `list`、`AgentExecutorRequest`、`AgentExecutorResponse`
- 只有 `AgentResponseUpdate`（role=assistant）带正文，且可能分段累积

`run_team()` 已处理这些差异，外部只拿 `turns / final / speakers`。

## 接口

`POST /api/automation/teams/run`

```json
{"agent_ids": ["<id>", "<id>"], "task": "给这家公司做能力缺口评估并出一道面试题",
 "mode": "group_chat", "max_rounds": 6, "approved": false}
```

- 成员必须是已有 `agent_profile`，1–4 个；工具一律取各自被授予的那份。
- `approved=false` 时写工具不执行，把「需批准」如实回给模型，保证这一轮安全跑完。
- 结果落一条 `workflow_run`，`data.kind="team"`，带完整 `turns / speakers / model_calls`，
  可在运行列表与详情里查看；团队运行不支持「入库确认」。

## 服务器现状（8771 已切换，8770 未动）

预览实例的真实目录**不是** `/opt/shilie/preview`——那里被
`shilie-preview.service.d/zzzz-preview-isolation.conf` 整体改名到
`/var/lib/shilie-preview/app`。改 `/opt/shilie/preview` 下的 venv 不会有任何效果。

实际完成：

```bash
# 1. 解释器：deadsnakes PPA 装 python3.12（3.12.16）
add-apt-repository -y ppa:deadsnakes/ppa
apt-get install -y python3.12 python3.12-venv python3.12-dev

# 2. 新 venv（与旧 .venv 并存，旧的可直接回滚）
cd /var/lib/shilie-preview/app
python3.12 -m venv .venv312
./.venv312/bin/python -m pip install -e ".[web]"
./.venv312/bin/python -m pip install agent-framework-core agent-framework-orchestrations
./.venv312/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
./.venv312/bin/python -m pip install sentence-transformers
chown -R root:shilie_pvapp .venv312

# 3. 切换：改 drop-in 里的 ExecStart，daemon-reload + restart
```

### 两个必须知道的坑

1. **`pip install -e ".[maf]"` 在服务器上会被静默忽略**：线上 `pyproject.toml` 是旧快照，
   没有 `[maf]` extra，pip 只提示不存在、照样装 web 部分。要么先部署新 pyproject，要么直接按包名装。
2. **kind 约束必须与代码的 `RECORD_KINDS` 完全相等**，多一个也不行。
   旧库里有 `eval_evidence`、代码里没有 → 启动即报「工作台kind约束未完整迁移或未验证」。
   约束属主是 `shilie_pvdb`（应用账号 `shilie_pvapp` 只有读写、无 DDL 权限），
   要用属主身份走本地 socket 改：

```bash
sudo -u shilie_pvdb psql -h /var/lib/shilie-preview/pgsock -p 55433 -d shilie_preview_20261104 \
  -c "ALTER TABLE workspace_records DROP CONSTRAINT workspace_records_kind_check, \
      ADD CONSTRAINT workspace_records_kind_check CHECK (kind IN (...))"
```

回滚：把 drop-in 的 ExecStart 指回 `.venv/bin/python`，`daemon-reload && restart`。

## 已知约束

- `agent_framework._types` 是内部模块（`Content.from_function_call` 等在这里），
  版本升级可能移动位置；已锁 `<2`，升级时先跑 `tests/test_maf_runtime.py`。
- 群聊每轮都要主持人做一次结构化决策（`terminate/reason/next_speaker/final_message`），
  token 消耗约等于「参与人数 × 轮次 + 1」次调用。
- 检查点目前用默认内存实现；要落库需把 `CheckpointStorage` 接到 PG（尚未做）。
- 未接真实模型验收：所有测试用假通道，只证明管线与协议正确，不证明生成质量。
