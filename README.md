# rag-tech-doc-retriever（技术文档 RAG 检索助手）

以 AIhuoke 真实生产文档（14 份）为主语料，验证 RAG 在技术文档场景下的检索效果，
覆盖数据预处理 → 向量检索 → 优化迭代 → Agent 工具调用 → MCP 协议适配 → 工程化封装全链路。
完整规范与阶段计划见 [AGENTS.md](AGENTS.md)。

## 运维与发布

运行诊断、发布门禁与 CI/发布包流程见 [运维说明](docs/OPERATIONS.md)。CI 定义未推送前不代表云端已执行；真实服务器 CD 尚未配置。

### 当前有效使用方式（2026-11-03 更新）

按用户确认，日常使用以**服务器为唯一后端与数据库**，不要求桌面启动 Docker 或本机网页进程。服务器采用 Ubuntu 原生 PostgreSQL/pgvector、Python venv 和 systemd，**双环境**：

| 环境 | 地址 | 服务 | 状态 |
|---|---|---|---|
| 正式 | `https://8.156.81.128:8770/` | `shilie.service` | v103 |
| 测试 | `https://8.156.81.128:8771/` | `shilie-preview.service` | v103（新功能先在此验证，独立数据库） |

两环境各自独立数据库（正式 `shilie_native_20261027`，测试 `shilie_preview_20261103`）并共用模型缓存，代码目录与 systemd drop-in 各自独立；数据库端口不对公网开放，ufw 仅放行本人 IP（云安全组需另行放行 8770/8771）。代码位于 `/opt/shilie/releases`，入口软链 `current`/`preview`，持久数据在 `/var/lib/shilie`，私密环境变量与证书在 `/etc/shilie`；代码切换不覆盖数据。

**登录方式**：账号密码（`WORKSPACE_USER` + `WORKSPACE_PASSWORD_HASH`，scrypt 哈希，存 `/etc/shilie/workspace.env`；用 `scripts/set_login_password.py` 交互生成，明文密码不入任何文件）+ 可选「记住此账号 30 天」；访问令牌登录保留为备用通道。

**部署流程**：`python scripts/deploy_release.py --target preview --apply --confirm HEAD` 推测试 → 浏览器验证 → `--target production` 推正式；失败自动回滚代码。CI 为 `.github/workflows/ci.yml`（全量门禁），测试环境可用 `Deploy preview`（workflow_dispatch，需配置 secrets `SHILIE_SSH_KEY` / `SHILIE_KNOWN_HOSTS`）；正式环境仍保持人工确认，不做 push-to-deploy。真实拓扑与全部踩坑（ProtectSystem 只读、site-packages 非 editable、kind 约束 8→17 等）见 [docs/DEPLOYMENT_REALITY.md](docs/DEPLOYMENT_REALITY.md)。

**质量门禁**：`scripts/local_gate.py`（pre-push hook 自动运行：ruff / pytest / 静态版本一致 / 敏感文件 / kind 与库一致）；完整门禁 `scripts/release_gate.py --checks full --backend native`（Docker 后端仅限 GitHub CI 显式选择）。

### 企业级能力（2026-11-03，v105）

- **统一能力目录**：`GET /api/capabilities/tools` 汇总内置工具、管理员 HTTP 工具与已启用 MCP 工具；Agent 工作室新增「能力绑定」，工具/技能/MCP 权限只来自保存的 Agent 配置。
- **联网搜索**：内置 `web_search`，默认 Bing CN（服务器网络可达），可切 Tavily（`TAVILY_API_KEY`）或 DuckDuckGo；固定供应商端点、禁止跳转、结果上限与缓存，搜索结果不改变权限。
- **管理员 HTTP 工具**：`config/agent-tools.yaml` 的 `http_tools` 只允许固定 HTTPS 主机与 JSON Schema 参数，模板不能改 URL/方法/请求头。
- **通用 DAG 工作流**：工作流支持 `input / retrieve / tool / agent / merge / approval` 节点；版本冻结、节点状态持久化、人工审批与结果合并。就绪节点按 `max_parallel`（1–4）并行执行，同波次失败/超时只影响本节点，多个并行 Agent 同时待确认时可一次批准，工作流页可新建 JSON DAG、运行与审批。
- **简历模块**：上传 PDF/DOCX/TXT/Markdown 后自动解析，公开记录只存元数据，解析文本存本机私密目录；支持结构化段落、技能命中、版本 diff 与 JD 对照（只做文本命中，不认定能力）。
- **OCR**：扫描版 PDF 与 PNG/JPEG 图片走 RapidOCR + PDFium，文本层不足时自动回退；依赖可选安装（`pip install -e ".[ocr]"`），未安装时文本版不受影响，图片上传明确报错，结果带 `ocr_used` 标记。
- **应用层加密**：AES-256-GCM（`platform/field_crypto.py`），密钥走 `SHILIE_ENCRYPTION_KEY` / 密钥文件，令牌绑定记录类型与字段名；开启后 `knowledge.content`、`job_lead.jd_text`、`resume_version.file_name` 与简历/周报私密文件在库里/磁盘为密文，读取透明解密，旧明文兼容。仓库默认关闭，服务器配置开启。
- **验证**：新增纯逻辑测试 31 项（并行调度 7 项、OCR/加密 15 项）；隔离 PostgreSQL 集成测试 35 项（DAG/求职/简历）与 Agent 回归 56 项通过；浏览器验收覆盖能力绑定、DAG 运行、真实简历上传与联网搜索。

### 当前待办（2026-11-03）

1. **真实 JD 人工确认**：10 份 AI/Agent JD 已完成执行方初核（10/10 合理，见协作记录）；10 份 AI 产品经理 JD 仅做学历/经验分析，尚未逐条人工签字。
2. **真实模型质量与七天使用**：模型连接、真实供应商质量、真实收件箱送达和连续七天使用仍需独立验收。
3. **后续演进**：DAG 仍是“波次内并发、波次间屏障”，未做跨波次动态补位；加密尚未做密钥轮换/离线恢复演练；联网搜索供应商仍受目标站点反爬策略影响，生产使用前应核对供应商条款。

下方本地启动、容器、旧测试数量及界面描述为按日期保留的历史/可选开发说明，不能替代上述当前使用方式或本轮验收。

## 时列 Web 工作台

本机开发入口为 http://127.0.0.1:8770/（可选，`./start-web.ps1 -Background` 启动，`./stop-web.ps1` 停止；本机测试库当前由 Docker 容器 `rag-pgvector` 提供——彻底去 Docker 的方案见下方待办）。日常使用请走服务器双环境。以下更新按时间保留，较早的页面描述不代表最新界面。

2026-10-19 已完成橙白主题、分叉规划树与私密滑块/表单修复；镜像构建和本机临时容器健康检查通过，真实服务器部署及实际模型供应商连通尚待验收。知识保存的阅读路径、用户练习 LEARN-001、模拟面试题及贡献边界集中在 [协作记录](output/web/collaboration/collab-log.md) 的“学习接手包”部分。自动任务负责检测和必要故障修复，用户练习不由它代写。

### 自动网页回归与恢复验证

Windows 本机需要已运行的 Docker Desktop、Chrome、Node/npm 和项目 `.venv`。首次缓存浏览器工具：

```powershell
npx --registry=https://registry.npmjs.org --yes --package @playwright/cli@0.1.22 playwright-cli --help
```

之后在项目根目录执行：

```powershell
.venv/Scripts/python.exe scripts/web_regression.py
```

脚本启动带随机名称和所有权标签的独立 PostgreSQL 容器、独立网页服务、临时私密元数据及 Chrome 会话，确认测试服务身份后才操作。覆盖知识创建/编辑/刷新、分叉规划/双击编辑/删除撤销/进度/居中、工作流入库与检索、私密内容与滑块、公共备份恢复及窄屏布局。随后真实停止/重启测试数据库，验证失败时保留输入、恢复后重试只保存一次；最后重启测试网页，确认数据和私密解锁仍可用。原生确认框在测试页面自动同意，删除结果另做断言。

快速只读检查（不建容器）：四场景浏览器回归 `node verify-ui.mjs all`（在含 playwright 依赖的目录执行，用法见 `scripts/verify-ui.mjs` 头部）；静态资源版本一致性 `.venv/Scripts/python.exe scripts/check_static_version.py`（改版升 vN 后运行，防止版本分裂导致"改了没反应"）。

全部通过退出码为 0，失败为非 0；结束时关闭测试浏览器和网页，仅在随机名称及标签均匹配后删除测试容器与它的临时卷。不停止正式数据库，不使用个人数据，也不运行真实模型。工具按缓存版本运行；缓存缺失时先执行上面的命令。若电脑重启或进程被强制结束，清理可能来不及执行，应先核对 `shilie-qa-*` 容器的 `io.shilie.regression` 标签和对应测试记录，再清理遗留资源。

公共 JSON/Markdown 备份包含知识、规划、Agent、流程及运行记录，排除私密愿望/日记与它们的历史；公共恢复也不会修改私密条目。私密内容使用下述独立加密包，或 PostgreSQL 备份与 `data/local/private-vault.json` 配套迁移，不能只靠公共 JSON。旧的含私密条目的混合备份不会自动转换。

### 私密加密备份与空目标恢复（2026-10-20）

本轮提供本机 CLI，**尚未增加网页备份按钮**。加密包包含愿望、日记、回收站、完整版本历史和口令校验元数据；不包含公共知识、向量、LLM 密钥。备份时不解密正文，外层强制 AES-GCM。备份口令独立于网页私密口令，至少 12 字符，只在交互终端隐藏输入，不接受管道或命令行明文口令。恢复后仍需原网页私密口令；加密包不是遗忘口令找回工具。

在项目根目录的 PowerShell 中使用（以下文件名为示例，导出不会覆盖同名文件）：

```powershell
./stop-web.ps1
.venv/Scripts/python.exe scripts/private_backup.py export data/local/exports/private-backup.json
.venv/Scripts/python.exe scripts/private_backup.py inspect data/local/exports/private-backup.json
# 仅在目标机器/数据库的私密区为空时运行，不要在已有私密内容的工作区演练：
.venv/Scripts/python.exe scripts/private_backup.py restore data/local/exports/private-backup.json --confirm 恢复到空私密区
./start-web.ps1 -Background
```

导出/恢复要求网页端口关闭，仍需人工确认没有其他实例写入同一数据库；不主动终止其他实例。恢复拒绝已有私密条目（包括回收站）、公共 ID 冲突及不同口令元数据，公共记录不改动。数据库记录/历史同一事务恢复，元数据先以不覆盖方式发布：数据库失败时可能保留同一份元数据，空私密区可用同一备份重试，不承诺文件系统与数据库跨资源原子提交。大小上限由 `config/web.yaml` 的 `web.private_backup_max_bytes` 控制，默认 64 MiB；文件系统须支持同目录硬链接，否则安全失败。备份包应另存到独立介质，留在同一硬盘不等于灾备；本轮不自动复制你的私密数据。

可重复的隔离恢复演练：`.venv/Scripts/python.exe -m pytest tests/test_private_backup.py -q`。使用随机专用表、临时元数据及虚拟口令，验证恢复后原测试口令从网页 API 解锁、历史/删除态一致、公共记录保留，以及损坏/错误口令/冲突/事务失败重试。不接触正式私密区；仅在本机 PostgreSQL 验证，真实服务器迁移未验。

### 定时维护结果契约（2026-10-20）

Windows 任务 `Codex-Agents-4h-QuotaGuard` 仍每 4 小时执行，模型 `gpt-6.1-sol`、推理 `xhigh`、周剩余额度严格 >5%。运行器位于 `E:/project/agents/.codex/agents-autopilot/runner.py`，父进程负责预检及运行中复查，不让受限子任务重复探测额度。

- `completed_changes`：源码实际变动清单一致，执行器提供验证和回滚编号。
- `checked_no_changes`：实际检查后无源码改动；`blocked`/`failed` 不当成完成。
- `skipped_quota`/`skipped_quota_unavailable`：额度不足或无法读取，未启动模型。
- `stopped_quota`/`stopped_quota_unavailable`/`stopped_time_limit`：运行中停止，不宣称修复完成。
- `failed_execution`/`failed_contract`：非零退出，或结果缺失/损坏/清单不符。
- `unverified_legacy`：旧版只凭退出 0 记录的“完成”，不能当作验收成果。

当前状态见同目录 `last-run.json`，新结果为 `last-result.json`，旧 `last-result.txt` 仅保留溯源。每轮先清旧结果，再要求 JSON Schema，并对比源码哈希（排除个人数据、密钥、output 日志）；验证文字仍是执行器报告，不等于父进程独立重跑测试。测试使用假执行器，不额外消耗一次模型任务。该 Windows 运行器不随服务器部署自动迁移，LEARN-001 仍留给用户。

本轮源码快照为 `20261020-100402-7e7948c5`；项目根外运行器/提示词的原件另保存在该阶段 `automation-before`。完整回退应先停止定时任务，恢复外部运行器/提示词，再使用项目阶段回滚预检；不要只移除项目内结果校验模块而保留新版外部运行器。阶段内 `ROLLBACK.sh` 只恢复传入的运行器副本，已在独立副本执行验证。

### 可操作、可组合的 Agent 接口（2026-10-20）

本轮是**能力接口与执行闭环**，不是新的拖拽工作流编辑器。可在本机 `http://127.0.0.1:8770/docs` 操作接口。旧网页仍使用固定检索/入库流程；新 Agent 运行记录使用独立接口，避免旧页面误当入库预览。配置只在服务器加载，修改 `config/agent-tools.yaml` 后重启网页。

安装依赖：`.venv/Scripts/python.exe -m pip install -e ".[web,dev]"`。MCP 使用已验证的官方 Python SDK **2.3.0**，不照搬旧版 ClientSession 示例；JSON Schema 使用 4.26.0。Dockerfile 加装 Git，compose 只读挂载工具配置、沿用 data/local 持久化；本机需将 Git 加入 PATH。配置其他 stdio 服务时，它依赖的可执行程序也必须在实际服务器/容器内存在。

| 接口 | 作用 |
| --- | --- |
| `GET /api/capabilities` | 内置工具、预算限制和能力状态；真实模型工具调用状态初始为未验证 |
| `GET /api/skills` / `GET /api/skills/{name}` | 技能目录 / 完整内容与 revision |
| `PUT /api/skills/{name}` | 导入 SKILL.md；创建 revision 为空，更新须携带读取到的 revision |
| `GET /api/mcp/servers` | 服务启用/信任状态，不返回命令、头信息或凭据 |
| `POST /api/mcp/servers/{id}/test` | 实际连接并发现服务器白名单工具，不执行工具 |
| `POST/PUT /api/agents[/{id}]` | 保存角色及 skill_ids/tool_ids/mcp_server_ids；编辑须当前 version |
| `GET /api/agents/{id}/tools` | 合并 Agent 获准的内置、Skill 激活及 MCP 工具 |
| `POST /api/agents/{id}/tools/call` | 无需 LLM 的手动工具调用，返回审计运行记录 |
| `POST /api/agents/{id}/run` | 模型选择工具→后端执行→回填结果→模型回答 |
| `GET /api/agent-runs` / `GET /api/agent-runs/{id}` | 运行摘要 / 冻结配置、调用结果和待确认操作 |
| `POST /api/agent-runs/{id}/confirm` | 批准或拒绝当前待确认操作，须 version 与 approve 布尔值 |

技能导入示例：`PUT /api/skills/knowledge-review`，正文为 `{"content":"---\nname: knowledge-review\ndescription: 整理资料时使用\n---\n先搜索已有知识，保留引用，只生成草稿。"}`。保存角色时增加 `skill_ids:["knowledge-review"]`、`tool_ids:["knowledge_search","knowledge_draft"]`、`mcp_server_ids:[]`；这些是实际生效字段，不是提示词里的装饰。旧角色默认空权限，旧网页编辑保留省略的绑定字段。

手动调用正文为 `{"version":1,"name":"knowledge_search","arguments":{"query":"Python","scope":"personal"}}`。模型运行正文为 `{"version":1,"query":"检索并整理我的Python知识"}`，需要该 Agent 的 generate=true、有效模型连接且供应商支持 tools/tool_calls。模型失败/空回答/循环超限会明确失败，不冒充已经执行；未配置模型仍可用手动工具、Markdown 入库及 GitHub 技能导入。

MCP 管理员配置例（默认 servers 为空，不会访问任何外部服务）：

```yaml
servers:
  docs:
    transport: streamable_http
    url: http://HOST:8770/mcp
    enabled: true
    trusted: true
    headers_env: {Authorization: MCP_DOCS_AUTHORIZATION}
    allow_tools: [search]
    readonly_tools: [search]
```

真实凭据由环境变量 `MCP_DOCS_AUTHORIZATION` 提供（含供应商要求的 Bearer 前缀），不放 YAML、Skill 或 Agent 提示词。stdio 改为 transport: stdio，配置 command、args 和 env_refs。网页 API 不接受这些启动参数。先调用服务 test，复制返回工具的 name，再加入 Agent 的 tool_ids，同时绑定 mcp_server_ids。服务白名单和 Agent 逐工具授权缺一不可；远程只读注解不作为权限。readonly_tools 是管理员声明，不是执行沙箱，必须先信任服务。

非只读调用返回 status=awaiting_confirmation，pending_calls 中有参数。向运行 confirm 接口提交 `{"version":RUN_VERSION,"approve":true}` 才执行，且每次只批准一个操作；false 拒绝。版本过期、角色权限变化、Schema 变化均拒绝执行。数据库 CAS 防止同一轮重复确认，但外部副作用和数据库不是分布式事务：服务中途崩溃可能留下 running/未知状态，不能盲目重试。来源内容或 Skill 不能自行扩大权限。内置 knowledge_get/planning_get 限定类型/范围，私密愿望与日记不作为工具开放。

#### Markdown 直接录入知识库

`POST /api/knowledge/import/markdown` 使用 multipart 文件字段 **file**：

```powershell
curl.exe -X POST http://127.0.0.1:8770/api/knowledge/import/markdown -F "file=@C:/path/notes.md"
```

支持 UTF-8（含 BOM）的 .md/.markdown，默认最大 256 KiB，正文最多 100000 字符；参数在 config/web.yaml。服务按标题/字数结构分析，返回 workflow_run 与待确认 chunks，**尚未写 knowledge**，不把结构解析称作 AI 总结。之后调用 `POST /api/workflow-runs/{id}/confirm`，正文 `{"version":RUN_VERSION,"selected":[0,1]}` 选择片段，原子写入；重复确认 409。标题为空、非法编码、二进制或超限有明确错误；只有标题没有正文的文件会产生 failed 运行记录。无需预先创建固定工作流或配置模型。

#### GitHub 下载/克隆技能

1. `POST /api/skills/github/preview`：`{"repo_url":"https://github.com/OWNER/REPO","ref":"main"}`。ref 可省略，仅支持公开仓库，不接受 token URL、SSH、本地地址或 tree 子页面。
2. 服务在临时隔离目录实际浅克隆，不 checkout、不加载 Git 全局配置、凭据助手、hook 或子模块。超时/下载体积监控超限会中止；这不是操作系统硬磁盘配额。返回 import_id、固定 commit SHA、技能全文及警告，先审阅。
3. `POST /api/skills/github/import`：`{"import_id":"IMPORT_ID","selected":["SKILL_NAME"],"confirm":true}`。创建同名冲突不覆盖；同一内容可重复提交。多技能逐一写文件，不承诺跨文件原子事务，I/O或并发冲突时可部分成功，重试会核对 revision。

首版**仅导入 SKILL.md**，不会安装依赖、执行仓库脚本、导入参考资源或部署任意 GitHub 项目；依赖这些资源的 Skill 尚不能完整运行。预览目录在 data/local/skill-imports，正式技能在 data/local/skills。部署迁移需同时携带技能目录及工具配置、重新配置服务器凭据；公共 JSON 恢复不会安装技能文件。后续可增加受控资源加载/沙箱执行，但不能把“下载”视为“信任并运行”。

上述接口统一受工作台令牌、同源写入与请求大小限制保护。首次配置先用只读工具，正式服务器须开启鉴权；按用户部署口径服务器一般使用 HTTP（无 TLS），令牌与内容在明文信道传输，适用于个人/内网场景——公网暴露时建议在 `config/mcp.yaml` 配置 `server.allowed_hosts` 白名单，或自行加 TLS/限制访问源。本项目仍是共享个人工作区，不是多租户平台。新增接口可在 Swagger 操作，前端管理页、任意节点编排、真实供应商模型和真实服务器连接另行验收。

2026-10-13 接入时列网页 Demo：中央入口/侧栏双模式、知识库、人生规划、任务依赖图与实时阶段记录。正文在网页输入，统一保存在 PostgreSQL；本机与服务器使用同一存储实现。前端无需 Node 构建。

```powershell
.venv\Scripts\python.exe -m pip install -e ".[web,dev]"
docker compose up -d db
./start-web.ps1 -SkipDatabase
```

后台启动可加 `-Background`；用 `./stop-web.ps1` 停止自己启动的后台应用，不会停 PostgreSQL 或其他项目进程。

若在 Codex 桌面环境直接启动 Docker 后出现 `sailor-ingest.sock` / error 1920，本机实测退出崩溃的 Docker 进程后，由资源管理器启动同一安装即可恢复。可从 Windows 开始菜单启动 Docker；不要在此错误下直接重置数据。一次恢复实测见 `output/web/docker-recovery-check.json`，相关启动上下文问题见 [官方仓库问题记录](https://github.com/openai/codex/issues/52698)。

打开 `http://127.0.0.1:8770`（端口取 `config/web.yaml` 的 `web.port`）。已有原始向量表的旧版本需要先执行 `scripts/migrate_namespace.py`；本机已完成迁移。新空库需要原来的 V1 初始化/入库脚本，个人知识与规划表会在启动时自动创建。

使用顺序：

1. **知识库**：新建知识，输入标题/正文/标签/来源。保存后可编辑、检索、查看历史，删除进入回收站。
2. **人生规划**：新建主线或支线 → 添加阶段 → 添加任务节点 → 选择前置任务。前置任务全部完成后自动解锁；后端拒绝循环依赖与错误完成顺序。
3. **阶段记录**：开始大阶段即保存源码与内容快照；结束时填写完成项、问题与验证，保存新增/修改/删除文件清单及文本 diff。源码回滚先预检，数据恢复会先留保护快照。
4. **导出备份**：JSON 包含内容、历史版本与阶段记录；Markdown 便于阅读。浏览器下载到你的电脑，应用另留存一份到 `data/local/exports/`。

「界面偏好」中的密度滑块实时调节列表和任务间距，支持键盘及刷新保留；导航模式、阅读位置和插画尺寸也保存在浏览器。保存与搜索显示请求状态，等待时阻止重复提交，失败保留输入；旧检索结果注明原查询词。任务完成和移除操作互斥，进度在服务端确认后更新。系统减少动画设置会关闭视觉过渡。

JSON 导入是**恢复内容并形成新版本**，保留现有数据库历史；不会把 JSON 中旧版本历史原样导入。需要原样迁移全部历史、向量与数据表，使用完整 PostgreSQL 备份。

知识条目、规划与历史在 `workspace_records` / `workspace_versions`；规划作为一个 JSONB 文档保存 storyline、act、node 与前置关系，整个规划树一次事务更新。`locked/available` 是派生态，不入库。需要更复杂的跨规划统计时再独立做关系表规范化迁移，不同时引入新变量。

### 模块分工

| 模块 | 职责 | 不承担 |
| --- | --- | --- |
| `api/static/shilie/data.js` | HTTP 请求、工作区数据、显示偏好与模块定义 | 页面布局与 SQL |
| `api/static/shilie/views.js` | 纯视图、表单结构和安全文字输出 | API 写入 |
| `api/static/shilie/app.js` | 路由、表单与操作协调、反馈和焦点 | 领域最终校验 |
| `api/static/shilie/{base.css,demo.css,icons.js}` | 视觉样式、响应式和 SVG 图标 | 业务状态 |
| `api/routes/{knowledge,planning,history,stages,search,exports}.py` | 请求契约、校验与服务组合 | SQL 与模型实现 |
| `domains/` | 内容、依赖、规划状态与备份规则 | HTTP、文件、数据库 |
| `platform/record_store.py` | 事务、行锁、版本、软删除与恢复 | 页面与领域规则 |
| `platform/search_service.py` | 跨域全文搜索、既有 RAG、可选 API 生成 | UI 与规划状态修改 |
| `common/stage_journal.py` | 阶段成果、源码快照、diff、回滚冲突保护 | 向量表恢复 |
| `rag/` | 原技术文档向量化、检索与重排 | 个人内容编辑 |

更新必须携带读到的 `version`，旧版本返回 409，不覆盖其他页面的修改。阶段日志与导出文件在应用宿主机落盘；服务器部署时对应服务器磁盘，可通过浏览器下载到个人电脑。

### 搜索与可选模型

时列 Demo 使用全文检索，覆盖个人知识、人生规划和原技术文档，并显示命中高亮。原完整界面保留在 `/legacy`，该界面及 API 支持可选语义检索；技术文档使用 pgvector 精确扫描 + bge-reranker，个人条目与规划仍为全文匹配。

生成回答可在网页「系统设置 → 模型连接」填写 API 地址、模型名和密钥，测试后保存，并在检索页勾选生成。网页配置保存到服务器私有的 `data/local/llm-connection.json`，不随知识备份导出；密钥留空保留旧值，保存后立即生效。未保存网页配置时仍读取环境变量或 `.env` 的 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`。BASE_URL 是 OpenAI 兼容接口的 API 根地址；未配置或调用失败时保留检索引用。日常打卡、AI 自动拆分、MCP/Agent 原计划扩展未在本轮实现。

### 阶段回滚与数据库备份

```powershell
.venv\Scripts\python.exe scripts\stage_checkpoint.py list
.venv\Scripts\python.exe scripts\stage_checkpoint.py rollback --id <阶段ID>
# 确认预检无冲突并停止应用后，再加 --apply
.venv\Scripts\python.exe scripts\stage_checkpoint.py rollback --id <阶段ID> --apply

```

数据库原生备份与**独立空库恢复**见 [NATIVE_BACKUP.md](docs/NATIVE_BACKUP.md)，按文档填写明确的数据库、角色和表前缀身份。默认不依赖 Docker；恢复不覆盖原库，不再提供原地 `--clean` 恢复。数据库口令仅走私有环境变量，不写命令或回执。升级/源码回退不会自动回滚数据库结构或业务数据。

源码回滚只覆盖本阶段实际改动文件，检测后续改动和备份摘要，冲突即拒绝。应用前另保存保护快照。源码与数据库分别恢复，源码回滚不会自动倒退数据库 schema。0-2 的独立向量恢复命令为 `scripts/migrate_namespace.py --restore --backup output/stages/20261012-01-core/vector_before.json`；需要先保存当前数据库，并确认没有新增其他域数据。

每个阶段目录另有只依赖 Python 标准库的 `recover_source.py`。即使源码回滚把主包/CLI 一并删除，仍能用 `.venv\Scripts\python.exe output\stages\<阶段ID>\recover_source.py --id <保护快照ID> --apply` 恢复回滚前源码。默认不加 `--apply` 只预检；换机器时加 `--root <新项目根目录>`。依赖环境和项目根外的技能安装不随源码回滚，数据库恢复独立执行。

### 历史容器部署说明（非当前部署方案）

当前服务器部署不使用本节的容器路线，且不采用明文 HTTP 公网登录。管理员应按上方原生使用方式与 `docs/NATIVE_SCHEMA.md`、`docs/NATIVE_BACKUP.md`、`docs/NATIVE_RELEASE.md` 核验现有安装，保留原库、有效配置、私密元数据和旧代码。通用 JSON 指针发布控制器不直接接管现有 `/opt/shilie/current` symlink/systemd 安装；不能只改指针声称完成升级。

默认数据库和应用宿主端口仅绑定回环。服务器部署按用户口径使用 HTTP 反向代理连接 `127.0.0.1:8770`，网页输入访问令牌登录；HTTP 下令牌为明文传输，仅适用于个人/内网场景，不要将未启用鉴权的应用直接暴露公网。这是一个共享个人工作区，尚未实现多用户账户与租户隔离。

`pgdata` volume 保存数据库，`data/local` 与 `output/stages` 的挂载保存导出和阶段快照。迁移时同时迁移数据库备份、这些目录与 `data/processed`，不是只复制源码。Linux 首次启动前确保挂载目录对容器 UID 10001 可写：`mkdir -p data/local output/stages && chown -R 10001:10001 data/local output/stages`。

轻量容器默认不安装大模型，提供全部内容管理与全文查询。若服务器需要语义检索，设置 `WITH_RAG=true` 重建镜像，并完成 V1 向量入库；首次加载模型需要联网，模型缓存使用独立 volume。Docker 安装包通过 `RAG_PROJECT_ROOT=/app` 找到项目配置，修正了 wheel 安装后按包目录寻找配置的问题。

本轮 `docker compose config` 通过；Docker Hub 鉴权域连接超时导致本机镜像构建未通过，因此没有宣称镜像运行或服务器部署已验证。原生 FastAPI 实际运行、API 与浏览器流程已验证；完整数据库备份在隔离数据库恢复 237 条向量成功。

### 验证记录

43 条 pytest 通过（含真实 PostgreSQL 事务/并发、API、规划反例、回滚实际执行与损坏备份）。浏览器验证网页输入、服务重启持久化、依赖解锁、知识历史恢复、阶段记录与数据恢复、JSON 下载；390px 四页无横向溢出。测试浏览器使用独立 `qa_browser_*` 表，未向个人生产知识库写入演示内容。

V1 **90%**、前缀 **80%**、V1.5 **100%**、Q08 **#7→#1** 全部复现；逐题结果无变化，语料与题集 SHA-256 不变。报告与截图在 `output/web/`、`output/playwright/`，最终交付报告见 `output/web/acceptance.md`。

## 快速开始

> 必须使用独立安装版解释器 `D:\python\python.exe`（Python 3.12.5）创建虚拟环境，
> 后续所有命令均通过 `.venv\Scripts\python.exe` 执行。

```powershell
D:\python\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## V0：语料切片与评测题集

```powershell
.venv\Scripts\python.exe scripts\ingest_md.py         # 切片 → corpus.jsonl（237 条）
.venv\Scripts\python.exe scripts\v0_generate_eval.py  # 生成评测题集（10 道，锚点强校验）
```

- 输入：`data/raw/aihuoke_docs/*.md`（只读归档；14 份 = 13 份生产文档 + SERVER_CHECKLIST.md）
- 输出：
  - `data/processed/corpus.jsonl` —— 237 条标准切片（`chunk_id` / `source_file` / `heading_path` / `content` / `meta.status_marker`）
  - `data/processed/eval_questions.json` —— 10 道评测题 / 11 个 must_retrieve 锚点（全部通过存在性校验）
  - `output/v0/v0_ingest_stats.json`、`output/v0/v0_ingest_console.txt` —— 统计快照与控制台报告

## V1：向量检索基线

```powershell
docker compose up -d db                                # 启动 PostgreSQL + pgvector（容器 rag-pgvector）
.venv\Scripts\python.exe scripts\v1_init_vector_db.py  # 建表（维度读 config/settings.yaml）
.venv\Scripts\python.exe scripts\v1_embed_and_index.py # 237 条向量化入库；当前配置 exact
.venv\Scripts\python.exe scripts\v1_run_baseline.py    # 基线评测 + query 前缀对照实验
```

- 实测结论（2026-10-10）：top-5 召回率基线 **90%**（9/10）；**加 instruction 前缀 -10pp**——与 bge v1.5「指令无关训练」口径一致（n=10 小样本，待扩展复核）
- 产物：`output/v1/v1_baseline_report.md`、`output/v1/v1_baseline_data.json`；账本自动入账 M003/M004

## V1.5：重排优化

```powershell
.venv\Scripts\python.exe scripts\v15_optimize.py   # 候选池 20 → bge-reranker-base 重排 → top-5（单变量对比）
```

- 实测结论（2026-10-10）：top-5 召回率 **90% → 100%（+10pp）**；V1 唯一失败题 Q08 从向量排名 #7 救回重排 **#1**，无失守；命中题名次普遍前移（如 Q01/Q05 #5→#1）
- 单变量声明：向量库 / 切片 / 评测集 / query 编码与 V1 基线完全一致，唯一变量 = 候选池后是否接入 CrossEncoder 重排
- 口径提醒：候选池 20 条（`retrieval.candidate_k`），重排只能对池内条目重排序；评测集 10 题，1 题即 ±10pp（延续 V1 口径）
- 产物：`output/v1.5/v15_optimize_report.md`、`output/v1.5/v15_optimize_data.json`；账本自动入账 M005
- 切片粒度 / 三层降级优化：V1 与 V1.5 均无对应失败点，按「不堆砌功能」原则暂不引入

## 量化成果账本（简历数据）

每个阶段/优化完成后记录一次「单变量改动 → 指标变化」，随时导出简历可用的成果清单：

```powershell
.venv\Scripts\python.exe scripts\record_metric.py add --stage V1 --topic "bge query 前缀对照" --metric "top-5 召回率" --baseline 40 --result 55 --unit "%" --variable "query 是否加 instruction 前缀" --sample "10 道评测题"
.venv\Scripts\python.exe scripts\record_metric.py list     # 查看全部记录
.venv\Scripts\python.exe scripts\record_metric.py export   # 导出 output/metrics_summary.md
```

- 账本存储：`output/metrics_ledger.jsonl`（一行一条，可直接手改后重新导出）
- 条目含 `domain` 维度（默认 tech_doc，幂等键 = 域+阶段+主题）；`list` / `export` 支持 `--domain <域>` 过滤，导出按「域 · 阶段」分组
- 口径提醒：导出时同时给出「百分点绝对差（pp）」与「相对提升%」两个口径，避免简历数字被追问时口径出错

## 阶段进度

| 阶段 | 状态 | 产物 / 结论 |
| --- | --- | --- |
| V0 环境准备 | 已完成 | `.venv`（Python 3.12.5，pip 26.2.1）；14 份原始文档归档 `data/raw/aihuoke_docs/` |
| V0 切片 | 已完成 | `corpus.jsonl` 237 条；状态分布 CONFIRMED 10 / PENDING 8 / DISABLED 10 / EXCEPTION 3 / UNKNOWN 206 |
| V0 评测题集 | 已完成 | `data/processed/eval_questions.json`：10 道题 / 11 个锚点 chunk，全部通过存在性校验；判定口径 = top-5 命中任一锚点 |
| V1 基线 | 已完成 | pgvector 入库 237 条（768 维）；top-5 召回率基线 90%；前缀对照 90%→80%（-10pp，v1.5 指令无关口径）；报告 `output/v1/v1_baseline_report.md` |
| V1.5 优化 | 已完成 | 接入 bge-reranker-base 重排（候选池 20）：top-5 召回率 90%→100%（+10pp），Q08 从 #7 救回 #1 且无失守；报告 `output/v1.5/v15_optimize_report.md` |
| V2-a 对照实验 | 已完成（2026-10-25） | 同套管线迁移公开文档（FastAPI 中文教程 8 页 + pgvector README + Python 标准库 pathlib/json，257 条，namespace=python_docs）；10 道题结果见 `output/v2/v2a_compare_report.md` |
| V2-b 状态感知 | 已完成（2026-10-25） | 状态显式标注已实现（引用上下文带状态、hits 携带 status_marker）；**降权排序实测负结果**（守护 100%→80% 且探针无收益，弱档位同样），默认关闭保留开关；报告 `output/v2/v2b_status_report.md` |
| V2-c 工具集 | 已完成（2026-10-24） | 栈解析/协议号查询/调试检索三件实现并接入 MCP server；见 tests/test_tools.py |
| V2-d Agent+MCP | 已完成（2026-10-24） | 固定流程 + AgentRuntime 写入确认；/mcp 官方 SDK 2.x Streamable HTTP（只读工具三件+语料资源）；旧手写 mcp/ 包已删除 |
| V2-e 工程化 | 已完成 | FastAPI 全路由 + Docker + 最小 CI；Dockerfile 已构建（10-19），服务器部署验收排在 W6-5 |

## 开发约定

- 配置优先：可变参数放入 `config/*.yaml`，敏感信息走环境变量（见 `.env.example`）
- 单变量迭代：每阶段只引入一个变量，所有结论以 `output/` 下的对比数据为准
- 测试：`.venv\Scripts\python.exe -m pytest`
- 代码格式：`.venv\Scripts\python.exe -m ruff check .`

### 2026-10-13 Demo 更新

进入首页后选择个人工作台，先新建笔记或人生规划。规划支持多主线/支线切换、P0–P4 与全部任务、状态筛选、任务编辑及前置关系；依赖图返回任务页，模块返回所属分类，分类返回首页。知识回收站可恢复删除的笔记；阶段可查看差异、运行只读回滚预检和恢复阶段数据。源码应用回滚仍由 CLI 执行，先停止应用并核对预检结果。

首页使用已确认的二次元国风插画，两档 WebP 资源和紧凑尺寸偏好。工作流与 Agent 设置已接入实际执行，使用方法见下面的本轮更新。实填 LLM API 调用及服务器部署仍需独立验收。

对应问题清单见 `output/web/mvp-issues.md`，交互证据见 `output/web/mvp-interaction-check.json`。完整旧界面保留 `/legacy`，独立设计稿保留 `output/web/design/`。


本次本地入口使用 `WEB_PORT=8770`，启动：`$env:WEB_PORT='8770'; ./start-web.ps1 -Background -SkipDatabase`；常规默认仍为 8766。最新验证：43 条测试、改动 Python 文件 Ruff、wheel 静态资源收录及 36 组布局检查通过；全仓 Ruff 的 142 项旧代码问题另行处理。


### 剧情章节、工作流和 Agent（2026-10-13）

人生规划 → 剧情章节：逐层展开主线/支线、章节、任务。章节可以先创建为空、填写阶段目标，再添加任务；任务可设定日期、P0–P4 和前置任务。等条件满足再完成任务，章节“待编排/可开始/等待前置/已完成”由真实任务派生。保留任务列表和依赖关系视图，折叠选择在本浏览器刷新后保留。章节标题允许相同，任务按章节 ID 归属。

自动化中心 → 工作流 → “启用基础流程”，由你点击后才在 PostgreSQL 创建一个知识助手和两条基础流程。Agent 设置可新建/编辑角色指令、允许检索的范围、引用数、全文/技术文档向量方式和生成开关；模型连接仍读取服务器 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL。无需配置模型就能保存资料与检索。

- 资料入库：粘贴正文或读取 UTF-8 Markdown/TXT → 按标题和配置字数解析 → 查看片段 → 选择并人工确认。预览不写知识库，确认以事务保存，重复确认不会重复入库。原文件不会修改。
- 检索回答：输入问题 → 仅在所选 Agent 范围内检索 → 保留编号引用 → 开启生成时尝试 API 回答。缺少模型、API 出错或没有依据都有明确状态，不编造执行成功。
- 运行记录：PostgreSQL 保存输入、当时的流程/Agent 配置版本、步骤耗时和结果，刷新可再次查看及确认未入库预览。列表展示最近 100 次，历史数据不删除。当前为同步短流程；中途服务退出的运行会停在“执行中”，记录不会自动续跑，请新建一次执行。

JSON 备份包含知识、规划、Agent、流程和运行记录及版本历史；Markdown 可读导出也包含配置与执行摘要。导入限制通过 config/web.yaml 的 web.max_import_bytes 调整，默认 32 MiB，与普通表单 2 MiB 限制分开。

安装/升级网页依赖使用 `.venv\Scripts\python.exe -m pip install -e ".[web,dev]"`，Web 包含经过本机验证的 LangGraph 1.2.15。编排在 agent/workflow_service.py，领域校验在 domains/automation.py，HTTP 路由在 api/routes/automation.py；前端由 automation-views.js / automation-actions.js / automation.css 分工。

本轮源码/数据快照与验证证据分别保存在阶段 20261014-094518-5737edee、20261014-100723-bcf938b4（ID 使用本机时间）。跨版本回滚前先导出最新数据，核对源码预检并恢复对应阶段数据，再恢复源码；仅回滚源码不能保证旧版本能读取新增自动化记录。数据库约束升级是增量兼容操作，不删除旧表或向量。

本轮验收：58条测试通过；Chrome实际操作链路和36组双模式布局通过；v12安装包包含15个静态资源。正式入口仍为 http://127.0.0.1:8770/，通过“人生规划→剧情章节”和“自动化中心→工作流”使用新增功能。真实模型服务与服务器部署尚未验证。

### 规划树（Web v13）
打开人生规划，选择「主线 / 支线」并创建方向。节点旁 ＋ 添加下一层，− 折叠分支；点节点在右侧编辑，也可更改所属父节点。父子连线仅表示组织层级，前置条件独立控制解锁。底部滑块缩放，拖动画布空白处平移，「定位根节点」回到起点。

各模块顶部提供「返回上一级」和「回到首页」。新增/更新/删除节点对应 `/api/plans/{id}/nodes` 接口，更新和删除要求当前版本；删除分支若仍被外部节点依赖会拒绝。数据保存到 PostgreSQL，历史版本与阶段快照保留。测试数据在独立表中，未写入个人工作区。

验证报告：`output/web/tree-verification.json`；预览截图：`output/web/tree-final.png`。

规划插画发布策略：网页使用 `planning-mist.webp`；本地 `planning-mist.png` 为保留原素材，不包含在 wheel 发布包中。请从干净构建目录打包，避免历史 build/lib 残留。

网页「数据与备份」现在支持 JSON 恢复：选择文件 → 预览新增/修改/移入回收站 → 勾选确认后恢复。预览后有新写入时会拒绝恢复，需重新预览。恢复前在事务锁内保存保护快照，可从阶段记录恢复；模型连接不参与恢复。恢复当前条目与回收站状态，保留当前历史，不导入备份中的旧历史和阶段文件。
