# 代码智能助手：三项能力的落点

目标：在工作台里下发一句任务描述，由多个 Agent 分工、读写代码、按流程交付，而不是让 AI 改宿主编译器。
这三项能力分别落在三个已有模块上，本文只记录**边界与开关**，实现细节看源码。

## 1. 代码直接编辑（新增）

`platform/code_workspace.py` + `platform/agent_capabilities.py`

工具（只有绑定了工作区的 Agent 才看得到）：

| 工具 | 写 | 说明 |
|---|---|---|
| `code_tree` | 否 | 列出目录，默认深度 3，跳过依赖/缓存目录 |
| `code_read` | 否 | 按行读取，返回行数与 `sha256`，写入前先核对 |
| `code_search` | 否 | 文本或正则搜索，返回 `路径:行号` |
| `code_patch` | 是 | 精确替换一段文本；`old_string` 必须唯一，返回 unified diff 与备份路径 |
| `code_write` | 是 | 新建或整体覆盖，覆盖已存在文件必须显式 `overwrite` |
| `code_shell` | 是 | 只跑管理员白名单里的命令前缀，不经 shell 解释 |

安全边界（缺一不可）：

- 根目录只能由管理员在 `config/agent-tools.yaml` 的 `code.roots` 登记；Agent 只能引用标识，不能填路径。
- 路径解析后必须仍在根目录内；绝对路径、`..` 越界、指向外部的符号链接一律拒绝。
- 读跳过 `.git/`、`data/local/`、`.env`/`*.pem`/`*.key`/`id_rsa*`；写额外拒绝 `.git/` 与密钥文件。
- 写入顺序固定：先备份到 `data/local/code-backups/<根>/...`，再写临时文件，最后 `os.replace` 原子替换。
- 只接受 UTF-8 文本，含 `\0` 的内容按二进制拒绝。

确认策略在 Agent 的 `workspace.write`：

- `each`（默认）：每次写入都暂停，等待人工批准，批准只对这一条生效。
- `run`：本轮第一条写入经人工批准后，本轮后续写入不再逐条暂停，但仍逐条记步骤、逐条备份。

`workspace.shell` 为真且 `code.shell.enabled` 为真时，才出现 `code_shell`。

## 2. 多 Agent 协作（复用并启用）

`agent/collaboration.py`：Supervisor 只能提出计划（`propose_plan`，必须人工批准），批准后按序 `call_worker`；
Worker 是受限子运行，产物回填黑板，越权交接、跳步、重放、预算超限都会停下并保留审计。
开关在 `config/collaboration.yaml` 的 `enabled`。

代码能力与协作天然叠加：Worker 用自己的 `workspace` 绑定，代码写入仍走它自己的确认门禁，
计划批准不等于写操作批准。

## 3. 任务级编排（重写）

`platform/workflow_composer.py`

- 产物是 `agents[]` + `workflow`：Agent 由模型按任务生成（key/名称/指令/工具/工作区），不再固定 `pm`/`dev`。
- 每个 Agent 依次过 `validate_agent` + `validate_binding`；工具必须在白名单内，代码工具不能手写，只能由工作区授予。
- 节点用 `agent` 字段引用 `agents[].key`；模板占位符是 `{{input.*}}` 与 `{{nodes.<id>.answer}}`。
- 草稿闭环：`compose/draft` 只返回草稿不落库 → `compose/revise` 按意见重出并给结构差异 → `compose/save` 才落库。
  保存时服务端重新校验，前端回传的权限字段不被信任。
- 内置两个规则模板：`generic`（规划 → 产出）、`code`（规划 → 实现 → 审查），规则模式不调用模型。

## 用法

1. 工作流页填一句话目标，选「通用任务」或「代码改动」，点「先出草稿审一遍」。
2. 看草稿里的 Agent、节点与工作区绑定，写修改意见点「按意见修订」，下方会列出增删改了哪些节点/连线/Agent。
3. 满意后点「确认并保存」，再点运行；执行到写入节点会暂停等你批准。
4. Agent 设置里给单个助手绑定工作区，就能在 Agent 工作室里直接对话改代码。

## 验证

`tests/test_code_workspace.py`（14 例：越界、软链、密钥、二进制、唯一匹配、备份、只读根、命令白名单、确认策略）、
`tests/test_workflow_composer.py`（18 例：任意 Agent、非法工具/工作区/引用被拒、修订差异、保存重校验）；
桌面断言 56 → 61（工作区表单、模板选择、草稿面板、修订差异、保存）。

`python scripts/ci_gate.py --desktop-ui`：8 项全过。
