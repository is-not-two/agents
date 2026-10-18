# rag-tech-doc-retriever（技术文档 RAG 检索助手）

以 AIhuoke 真实生产文档（14 份）为主语料，验证 RAG 在技术文档场景下的检索效果，
覆盖数据预处理 → 向量检索 → 优化迭代 → Agent 工具调用 → MCP 协议适配 → 工程化封装全链路。
完整规范与阶段计划见 [AGENTS.md](AGENTS.md)。

## 时列 Web 工作台

2026-10-13 接入时列网页 Demo：中央入口/侧栏双模式、知识库、人生规划、任务依赖图与实时阶段记录。正文在网页输入，统一保存在 PostgreSQL；本机与服务器使用同一存储实现。前端无需 Node 构建。

```powershell
.venv\Scripts\python.exe -m pip install -e ".[web,dev]"
docker compose up -d db
./start-web.ps1 -SkipDatabase
```

后台启动可加 `-Background`；用 `./stop-web.ps1` 停止自己启动的后台应用，不会停 PostgreSQL 或其他项目进程。

若在 Codex 桌面环境直接启动 Docker 后出现 `sailor-ingest.sock` / error 1920，本机实测退出崩溃的 Docker 进程后，由资源管理器启动同一安装即可恢复。可从 Windows 开始菜单启动 Docker；不要在此错误下直接重置数据。一次恢复实测见 `output/web/docker-recovery-check.json`，相关启动上下文问题见 [官方仓库问题记录](https://github.com/openai/codex/issues/52698)。

打开 `http://127.0.0.1:8766`。已有原始向量表的旧版本需要先执行 `scripts/migrate_namespace.py`；本机已完成迁移。新空库需要原来的 V1 初始化/入库脚本，个人知识与规划表会在启动时自动创建。

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

.venv\Scripts\python.exe scripts\database_backup.py backup --file output\backups\workspace.dump
.venv\Scripts\python.exe scripts\database_backup.py restore --file output\backups\workspace.dump
# 先做新的保护备份、停 app，再加 --apply 恢复整个数据库
```

源码回滚只覆盖本阶段实际改动文件，检测后续改动和备份摘要，冲突即拒绝。应用前另保存保护快照。源码与数据库分别恢复，源码回滚不会自动倒退数据库 schema。0-2 的独立向量恢复命令为 `scripts/migrate_namespace.py --restore --backup output/stages/20261012-01-core/vector_before.json`；需要先保存当前数据库，并确认没有新增其他域数据。

每个阶段目录另有只依赖 Python 标准库的 `recover_source.py`。即使源码回滚把主包/CLI 一并删除，仍能用 `.venv\Scripts\python.exe output\stages\<阶段ID>\recover_source.py --id <保护快照ID> --apply` 恢复回滚前源码。默认不加 `--apply` 只预检；换机器时加 `--root <新项目根目录>`。依赖环境和项目根外的技能安装不随源码回滚，数据库恢复独立执行。

### 服务器部署

```bash
# 配置 .env：数据库密码、随机长 WORKSPACE_ACCESS_TOKEN、WORKSPACE_REQUIRE_AUTH=true
docker compose up -d --build
```

默认数据库和应用宿主端口仅绑定回环。通过服务器 HTTPS 反向代理连接 `127.0.0.1:8766`，网页输入访问令牌登录；不要将未启用鉴权的应用直接暴露公网。这是一个共享个人工作区，尚未实现多用户账户与租户隔离。

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
| V2-a ~ V2-e | 待开始 | 对照实验 / 状态感知 / 工具集 / Agent+MCP / 工程化 |

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
