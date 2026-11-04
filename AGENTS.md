# AGENTS.md
## Project Overview
### 项目名称
技术文档RAG检索助手（rag-tech-doc-retriever）

### 项目定位
纯Python技术栈实现的智能技术文档检索工具，以真实生产系统内部文档为主测试语料，后续补充公开技术文档做对照实验，验证RAG在不同结构技术文档下的检索效果。覆盖数据预处理、向量检索、优化迭代、Agent工具调用、MCP协议适配、工程化封装全链路能力。

### 核心目标
1. 产出可运行、可演示、有完整数据支撑的Python+RAG项目，匹配Python后端/AI应用开发岗技术要求
2. 通过真实业务文档场景，体现对复杂技术系统的理解能力
3. 所有技术优化都配套量化对比数据，不堆砌功能
4. 模块解耦、分层清晰，支持后续扩展能力

### 执行原则
- 小步快跑、单变量迭代，每个阶段只引入一个变量，确保失败点可精准归因
- 先跑干净基线再针对性优化，所有结论都有数据支撑
- 配置与代码分离，可变参数全部抽离配置文件，不硬编码
- 模块单向依赖，下层不依赖上层，替换组件不改动核心逻辑
- 符合Python工程规范，遵循标准打包结构

## Tech Stack
全程纯Python生态，无PHP开发依赖

| 层级 | 技术选型 | 关键参数与约定 |
|------|----------|----------------|
| 开发语言 | Python 3.10+ | 优先使用标准库，最小化第三方依赖 |
| 嵌入模型 | bge-base-zh-v1.5 | 768维；query侧前缀按实测口径（v1.5 不加更优，见 Key Notes 1）；维度抽离为配置项 |
| 重排模型 | bge-reranker-base（CrossEncoder） | V1.5 候选池精排（candidate_k=20）；打分降序、同分保持原序；仅重排池内条目（见 Key Notes 5） |
| 向量数据库 | PostgreSQL + pgvector | psycopg2驱动；当前精确扫描（历史 V1 用 IVFFlat）；建表维度读取配置生成 |
| 后端框架 | FastAPI | 轻量REST接口封装 |
| Agent编排 | LangGraph | 意图识别 + 工具路由 + 状态机流程 |
| MCP协议 | 官方 Python SDK 2.x | 客户端 stdio/Streamable HTTP；对外服务端 `/mcp` Streamable HTTP 已上线（只读工具三件+语料资源） |
| 工程化 | 原生 systemd + PostgreSQL（服务器） | 双环境 8770/8771；Docker 仅限本机测试库与 GitHub CI（去 Docker 方案待执行） |

## Full Project Structure
符合PEP 517标准src-layout结构，单向依赖分层：`common → rag → agent → mcp → api`

```
rag-tech-doc-retriever/
├── AGENTS.md                    # 本文件：项目完整记忆与规范
├── README.md                    # 项目说明、启动指南、阶段进度记录
├── pyproject.toml               # 项目元数据、依赖管理、构建配置
├── requirements.txt             # 依赖清单（兼容旧模式，按阶段按需安装）
├── .env.example                 # 环境变量模板（敏感信息不入库）
├── Dockerfile                   # 镜像构建文件
├── docker-compose.yml           # 一键部署编排文件
├── .gitignore                   # 版本控制忽略清单（.env/.venv 等不入库）
├── config/                      # 全局配置中心（非代码配置）
│   ├── settings.yaml            # 主配置：模型参数、向量库、切片、检索、Agent阈值
│   ├── prompts.yaml             # 系统提示词、指令前缀、回答模板、工具描述
│   └── mcp.yaml                 # MCP协议配置：工具暴露、权限、资源映射
├── data/                        # 数据层（原始数据只读，加工数据可写）
│   ├── raw/                     # 原始文档库，只读不修改
│   │   ├── aihuoke_docs/        # 主语料：14份AIhuoke真实生产文档（V0/V1基线用）
│   │   ├── python_docs/         # 辅助语料：Python公开技术文档（V2-a对照实验用）
│   │   └── aux_docs/            # 对照语料候选归档（V2-a备用，如 atguigu 客服知识库）
│   └── processed/               # 加工后的结构化语料
│       ├── corpus.jsonl         # 标准切片语料库
│       └── eval_questions.json  # 评测题集（含must_retrieve客观判定字段）
├── src/
│   └── rag_tech_retriever/      # 【主包】Python标准src-layout包结构
│       ├── __init__.py
│       ├── common/              # 通用基础层（被所有上层依赖）
│       │   ├── __init__.py
│       │   ├── config_loader.py # 配置加载器，支持环境变量覆盖配置文件
│       │   ├── utils.py         # 通用工具函数、文本处理、格式转换
│       │   ├── constants.py     # 全局常量定义
│       │   ├── metrics_ledger.py # 量化成果账本（记录各阶段改进前后对比，供简历/汇报取数；条目带 domain 维度）
│       │   └── middleware/      # 全链路通用中间件
│       │       ├── logger.py    # 结构化日志中间件
│       │       ├── cache.py     # LRU缓存中间件（检索结果、工具解析结果）
│       │       ├── exception.py # 全局异常类与统一错误码
│       │       ├── tracer.py    # 调用链路追踪中间件
│       │       └── rate_limiter.py # 接口限流中间件
│       ├── rag/                 # 【RAG核心引擎层】
│       │   ├── __init__.py
│       │   ├── data_processor/  # 数据预处理模块（V0阶段）
│       │   │   ├── markdown_parser.py   # Markdown标题层级解析
│       │   │   ├── slice_strategy.py    # 切片策略：标题层级+字数兜底
│       │   │   ├── status_extractor.py  # 协议号段状态标记正则提取
│       │   │   └── corpus_writer.py     # JSONL标准格式输出
│       │   ├── embedding/       # 嵌入模型模块（V1阶段）
│       │   │   └── bge_embedder.py      # bge模型封装，内置query前缀逻辑
│       │   ├── vector_store/    # 向量数据库模块（V1阶段）
│       │   │   ├── pgvector_client.py   # pgvector连接与CRUD封装
│       │   │   └── schema.py            # 建表语句，维度读取配置生成
│       │   └── retrieval/      # 检索核心模块（V1.5/V2-b阶段）
│       │       ├── base_retriever.py    # 基础向量检索
│       │       ├── reranker.py          # 重排算法
│       │       ├── status_filter.py     # 业务状态感知降权逻辑
│       │       └── level_matcher.py     # 三层降级匹配机制
│       ├── agent/               # 【Agent编排层】（V2-d 原规划五模块已被替代实现取代并删除，2026-10-24）
│       │   ├── __init__.py
│       │   ├── capability_runtime.py # AgentRuntime：模型→工具→模型循环、写入确认、限额（未入 git 基线）
│       │   └── workflow_service.py   # LangGraph 固定流程：知识处理+人工确认、检索+可选生成
│       ├── tools/               # 【原子工具集】供Agent调用（V2-c阶段）
│       │   ├── __init__.py
│       │   ├── protocol_query.py    # 协议号精准查询工具
│       │   ├── stacktrace_parser.py # 通用异常栈解析工具
│       │   └── debug_retriever.py   # 检索调试工具
│       ├── mcp/                 # 【MCP协议适配层】（V2-d扩展）
│       │   ├── __init__.py
│       │   ├── server.py          # MCP标准协议服务端
│       │   ├── tool_adapter.py    # 原子工具转MCP标准工具适配器
│       │   ├── resource_provider.py # MCP资源访问提供者
│       │   └── permission.py      # MCP工具权限控制
│       └── api/                 # 【对外接口层】（V2-e阶段）
│           ├── __init__.py
│           ├── main.py            # FastAPI启动入口
│           ├── dependencies.py    # 接口依赖注入
│           └── routes/
│               ├── chat.py        # 对话检索接口
│               ├── mcp.py         # MCP协议端点
│               └── admin.py       # 管理接口
├── scripts/                     # 各阶段可直接执行脚本，按命名顺序执行
│   ├── v0_validate_structure.py # 【第一步】单份文档标题结构验证（20分钟）
│   ├── v0_process_corpus.py     # V0：全量文档切片输出JSONL
│   ├── v0_generate_eval.py      # V0：生成评测题集
│   ├── v1_init_vector_db.py     # V1：初始化向量数据库表结构
│   ├── v1_embed_and_index.py    # V1：批量向量化入库
│   ├── v1_run_baseline.py       # V1：跑基线评测+前缀对比实验
│   ├── v15_optimize.py          # V1.5：针对性优化脚本
│   ├── v2a_add_python_docs.py   # V2-a：补充Python文档对照实验
│   ├── v2b_enable_status.py     # V2-b：启用状态感知功能
│   ├── v2e_start_api.py         # V2-e：启动FastAPI服务
│   └── record_metric.py         # 量化成果账本（记录/导出简历数据，跨阶段通用）
├── tests/                       # 单元测试（与主包结构一一对应）
│   ├── conftest.py              # 测试配置与fixture
│   ├── test_rag/
│   ├── test_agent/
│   └── test_tools/
└── output/                      # 各阶段输出产物、报告、日志
    ├── v0/                      # V0切片统计、抽样检查结果
    ├── v1/                      # V1基线报告、前缀对比数据
    ├── v1.5/                    # V1.5优化前后对比报告
    └── v2/                      # V2各阶段测试报告、接口日志
```

### 结构与磁盘的差异（2026-11-03 核对，权威视图见工作区根 DESIGN.md §2）

上方结构树是 V2 规划时代的快照，实际磁盘已演进为工作台形态，主要差异：
- `src/rag_tech_retriever/platform/`（27 模块：record_store/private_store/search_service/agent_capabilities/web_search/http_tools/resume_service 等）与 `domains/`（10 模块纯校验层）为现行核心，未在上方树中；`agent/` 现为 capability_runtime/graph_runner/collaboration/evaluation 等 **10 模块**（2026-11-03 删除两个空壳后）
- 2026-11-03 包卫生清理：删除 **10 个零引用 docstring 空壳**（`agent/rag_graph.py`、`agent/tool_executor.py`、`common/constants.py`、`common/utils.py`、`rag/data_processor/*`（4 个）、`rag/retrieval/base_retriever.py`、`level_matcher.py`），其职责已由 `graph_runner`/`capability_runtime`/`platform.search_service` 承担；新增 `tests/test_package_hygiene.py` 钉住「包内不得再有只有 docstring 的模块」，`ruff` 全过、OpenAPI 契约仍 `paths=114`。
- `api/routes/` **21 个路由模块**（OpenAPI 实测 **114 paths / 149 operations**，含检索评测 `/api/eval/*` 与能力目录）；前端 `api/static/shilie/` **28 个 JS 模块，静态版本 v108**（含 evaluation.js、company-capabilities.js）
- 2026-11-03 企业级补强（已提交 `6c973ed`，已部署测试环境，正式未动）：图工作流消费 `max_retries`，支持节点级 `retry`（仅 timeout/tool_error）、`timeout_s`、`on_error=fail|continue|fallback`、`join_policy=any_success`、跨波次动态补位、`node_attempts` 审计；`POST /api/workflow-runs/{id}/resume` 仅恢复只读节点，Agent 节点拒绝自动恢复。前端知识搜索 120ms 防抖 + `#knowledge-panel` 局部渲染、409 冲突对话框、相关笔记；`/api/query`、`/api/knowledge`、`/api/jobs` 增加 response_model；`/api/status` 与 `/api/admin/stats` 改用计数查询。本机纯逻辑测试 29 项通过（DAG 14、契约 4、其余既有），全量 800+ 未跑（缺隔离 PG）；preview 健康、数据基线、OpenAPI 契约已真实 HTTP 复核；登录后交互由 2026-11-03 后续轮次补充验收。
- 2026-11-03 批次 D 后端收口：`/api/status` 的 node/done 计数改 JSONB 聚合（`RecordStore.plan_stats`，新增与内存统计的口径对照测试）；`protect` 请求体限长改按块计数（`api/request_guard.py`，已知超限不读正文、chunked 也不整包缓存，下游解析不受影响）；鉴权抽到 `api/auth.py`（`Authenticator` + 会话签发/校验，规则不变）。新增纯逻辑测试 9 项（鉴权 5、限长 4），本机 42 项纯逻辑 + ruff 全过。
- 2026-11-03 前端批次 B+C（v107，已部署测试环境）：断点收敛为 639/1279/1280（保留 <960 环轨与 <420 漏斗子断点），S 档底部主导航（aria-current）、44px 触摸目标、安全区留白；首屏骨架屏；`back()` 改 `BACK_ROUTES` 回退表。Playwright 对预览做 7 宽度 × 2 页面矩阵：零横向溢出、导航仅在 <640 显示、零控制台错误，回退表落到 `#category/workspace`；截图在 `output/web/preview-v107/`。登录后真实交互仍需账号复验。
- 2026-11-03 门禁补强（`3bc86c0`，已部署 preview `native-20261103-205133-3bc86c0`）：OpenAPI 契约漂移检查进入 `release_gate.py` quick/full 与 `local_gate.py` 阻塞链（此前只有独立脚本），门禁单元测试钉住「命令在链上 + 漂移即阻断」；本机 `release_gate --checks quick` GATE_PASS，服务器 release 内契约 `paths=114` 稳定、门禁测试 8 passed。顺带修复 `local_gate.py --report` 相对路径 `ValueError`。服务器隔离全量 926 passed 证据仍对应前一 HEAD，本轮未重跑。最新 HEAD 已在 preview 真实验证登录与检索：`POST /api/session` 200 authenticated、`GET /api/knowledge` 200、`POST /api/query`（text）200 `engine=全文匹配`；真实 Edge/Playwright 经 SSH 转发验收账号模式登录 → `#home` 渲染、零控制台错误（截图 `output/ci/server/preview-login-home.png`）。真实读写闭环（`output/ci/server/verify_preview_flows.py`）：新建知识 201(v1)→列表可见→更新 200(v2)→历史 2 版→文本检索 200(7 hits)→软删除 200→回收站可见，验收记录随后物理清理，preview 恢复 55 条记录 / 0 知识 / 0 版本；更深层模块交互（求职/规划/备份页面）仍待逐页验证。逐页渲染验收（`output/ci/server/verify_preview_pages.mjs`）：登录后遍历 20 个路由，0 页异常、0 控制台错误，截图在 `output/ci/server/pages/`。收藏/求职/规划写操作闭环（`output/ci/server/verify_preview_features.py`，16 步全过）后按 id 物理清理，preview 回到 55 条记录 / 0 孤儿版本。
- 2026-11-03 备份恢复补齐收藏/谨记（`b9d9ad4`，已部署 preview `native-20261103-214813-b9d9ad4`）：`validate_snapshot` 曾缺 `bookmark`/`lesson` 校验器——导出可以包含这两类，导入预览/恢复却整包 400，用户建过收藏或谨记后无法恢复备份。现把校验器抽为 `SNAPSHOT_VALIDATORS` 并补齐两类，新增 3 例回归（注册表覆盖、两类可恢复、未注册类型仍拒绝）；`ruff` 全过、`local_gate --quick` 7/8 PASS（pytest 按 quick 跳过）。部署前清理 10 个当日旧 release（磁盘 1.6G→19G），部署后健康 ok、55 条记录 / 819 条向量未变。深层模块写操作闭环（`output/ci/server/verify_preview_modules.py`）：谨记建/改；复习卡建→评分 3→历史 1 条→同 `request_id` 重放返回 `replayed`；岗位→投递→PATCH 推进 `interviewing`→面试复盘→按薄弱点建卡；通知摘要预览→入队→取消；导出 JSON→导入选项→导入预览 200 且含 `snapshot_hash`；阶段列表/汇总只读（preview 无阶段）、私密状态只读（已配置）。全部通过后按 kind 物理清理 22 条记录 / 32 版本并删除 4 个验收导出文件，preview 回到 **55 条（28 有效）/ 102 版本 / 0 孤儿**。
- 2026-11-03 MCP 端点两处真实缺陷（`224b7a6` + `998a50e`，已部署 preview `native-20261103-220400-998a50e`）：① 挂载点 `/mcp` 被 Starlette 307 到 `/mcp/`，MCP 客户端按文档地址直连会握手失败——新增 `mcp_path_alias` 中间件把 `path`/`raw_path` 归一化，两种写法等价；② `rag://corpus/chunks` 用静态 `add_resource` 注册，只能列出、`resources/read` 必然报错——改为 handler 注册（内容仍是构建时快照）。新增回归 2 例（`/mcp` 免重定向、资源可读且库不可用时如实标注）。官方 MCP Python SDK 2.3.0 真实客户端（`output/ci/server/verify_mcp_sdk_client.py`，会话 Cookie 鉴权、不读令牌值）全过：initialize 协议 2025-06-18、tools/list 5 工具全 readOnly、search_docs 10 hits（`pgvector-README::001`）、未注册工具报 `Unknown tool`、resources/read `namespace=tech_doc` / `total_chunks=237`。M10 桌面客户端配置仍未验证。
- 2026-11-03 破坏性路径真实验收（preview，`output/ci/server/verify_preview_destructive.py`，全步骤 `ok:true`）：阶段创建 201 → 列表/汇总/差异 → 结束 200（`status=attention`，`passed` 必须带验证证据）→ 回滚预检 200（未结束阶段返回 400「只能回滚已结束的阶段」）；新建临时知识后用该阶段「恢复数据」200，`GET /api/knowledge` 回到空、有效记录集合与基线一致，并生成“数据恢复前保护快照”阶段；`/api/export` + `/api/import/preview` + `/api/import` 走通整体恢复（内容一致时 `restored_records=0` 为幂等空操作），生成“数据导入前保护快照”阶段。清理：删除 17 个测试阶段目录（约 115MB）与全部导出文件、物理清理临时知识，preview 复核 `55 条（28 有效）/ 0 孤儿版本 / 0 阶段`；版本 102→110 系恢复事务追加的历史（append-only，记录集合未变）。私密口令写入未动（preview 已配置口令，覆盖属全局破坏性操作）。
- 2026-11-03 前端接口契约入禁（`cbab42b`，预览 `native-20261103-222335-cbab42b`）：新增 `scripts/frontend_api_contract.py`，扫描 shilie 前端 `api("…")`/`fetch("/api/…")` 引用并与 `docs/openapi.json` 按路径形状逐段比对（`${id}`≡`{record_id}`、动态拼接按前缀），无库无服务、0.5s；接入 `release_gate.py` 命令链与 `local_gate.py` 阻塞项。结果前端 **84 条引用与 114 条路径完全一致**；本机 `local_gate --quick` 8/9（1 跳过）、`release_gate --checks quick` GATE_PASS。顺带删除 `api/routes/private.py` 的 `import os` 与 `_ = os` 占位引用，部署后真实 HTTP 复核 `/api/private/status` 200、`/api/private/wish` 401「需要有效的解锁票据」且信封完整。
- 2026-11-03 静态资源卫生（`362c211`，预览 `native-20261103-222840-362c211`）：删除静态目录里的编辑器备份 `app.css.bak-before-blackhole`（134KB，会随 release 发布且公网可访问）；`tests/test_package_hygiene.py` 增加静态残留不变式（`.bak/.tmp/.orig/~/.swp` 一律失败）。部署后复核：该文件 **404**、线上 `/openapi.json` **114 paths / 149 ops** 与快照同集合、Edge 登录后 **20 个路由 0 异常 0 控制台错误**。
- 2026-11-03 登录失败限速（`3889797`，preview `native-20261103-223554-3889797`）：`api/auth.py` 新增 `LoginThrottle`，按客户端地址累计失败（默认 10 次/300 秒），`/api/session` 先查封锁、失败计数、成功清零；429 带 `Retry-After` 与统一信封 `RATE_LIMITED`。配置 `web.login_max_failures` / `web.login_window_seconds`；`docs/openapi.json` 同步。本机 `pytest tests/test_auth_module.py` 7 passed、ruff 全过；真实 preview：10×401 后第 11 次 429（Retry-After 300），封锁期正确口令同样 429，`systemctl restart shilie-preview` 清空内存计数后 200。**边界**：内存态计数，多 worker 需换共享存储；进程重启即清空。
- 2026-11-03 前端资源修复（`8cad566` + `71912e9`，preview `native-20261103-224435-71912e9`）：删除审计已判定的孤儿 `shilie/planning.js` 与 `chapters.css`；`tree.css` 两处坏引用 `./assets/landscape-1600.webp`（仓库无 `assets/`）改为 `./planning-mist.webp`；新增 `scripts/check_static_assets.py` 校验 index.html 与 CSS 的本地引用并入双门禁（本机 9/10、GATE_PASS）；`api/main.py` 登记 `image/webp`。部署后真实 HTTP：孤儿文件 404、`planning-mist.webp` 与 `landscape-1600.webp` 均 `200 image/webp`（修复前是 octet-stream）、svg/png 类型正确、20 路由 0 异常。
- 2026-11-03 传输与运维收口（`f807f8c` + `9028e4a`，preview `native-20261103-225343-9028e4a`）：启用 `GZipMiddleware`（app.css **177,358→43,762 bytes**，约 75%），响应补 `Referrer-Policy: no-referrer`；`deploy_release.py` 增加 `--keep-releases`（默认 2）并在成功后清理旧 release——`current`/`preview` 软链目标永不删除，失败只告警不回滚；新增 `tests/test_deploy_prune.py` 3 例。实测：MCP/SSE 未被压缩影响（SDK 全链通过）、20 路由 0 异常、服务器 release 目录 3.0G→17G 可用（保留正式 + 当前 + 2 个历史）。
- 2026-11-03 契约检查器补盲区（`29cde61`，preview `native-20261103-230059-29cde61`）：`frontend_api_contract.py` 原正则只认同一行字面量，导致 42 条路径误报“前端未引用”、并漏检 3 条跨行/拼接调用；改为允许换行 + 按段前缀匹配，抽出 `extract_calls` 并新增 `tests/test_frontend_contract.py` 3 例。结果：**87 条前端引用 / 114 条 OpenAPI 路径全部一致**；用改进匹配复核全部前端 JS（含 legacy），仅 `/`、`/health`、`/health/live`、`/health/ready`、`/legacy` 不由 JS 调用（均为入口/探针/待退役旧前端），**无孤儿业务端点**。
- 2026-11-03 错误信封补洞（`66adfab`，preview `native-20261103-230627-66adfab`）：非法输入抽样 19 组发现 405 返回裸 `{"detail":"Method Not Allowed"}`、无 code/request_id（根因是只给 `fastapi.HTTPException` 注册了处理器，Starlette 的 404/405 走默认响应）；改为注册 Starlette 基类 + 新增只追加码 `METHOD_NOT_ALLOWED` + 中文默认文案。真实响应复核：405 → `该接口不支持此方法/METHOD_NOT_ALLOWED/request_id`、404 → `接口不存在/NOT_FOUND/request_id`；抽样 19 组全部 4xx 且有信封、0 个 5xx。`tests/test_error_contract.py` 新增 2 例（需实库，随 CI 跑）。
- 2026-11-03 导出不再常驻磁盘（`cbbdb7e`，preview `native-20261103-231038-cbbdb7e`）：`/api/export` 原来每次点击都在 `data/local/exports` 留一份 253KB JSON / 26KB Markdown，目录单调增长；改为 `FileResponse` + `BackgroundTask(remove_export)` 下载后删除，新增 `tests/test_export_cleanup.py` 2 例。实测：json/markdown/再 json 三次下载均 200 且文件名正确，服务器 exports 目录 **total 0**。
- 2026-11-03 数据库连接池（`6850925` + `ec9d769`，preview `native-20261103-232849-ec9d769`）：`RecordStore` 由「每事务新建连接」改为可选 `ThreadedConnectionPool`（`web.db_pool_size=8`，`0` 保持旧行为；惰性创建、建池失败回退直连，`lifespan` finally `close()`）。实测 `/api/status` p50 **62→13ms**、p95 **66→14ms**（服务器回环 25 次采样）。随后补两处健壮性：`web.db_pool_wait_seconds=5` 借满按 20ms 步进等待（`ThreadedConnectionPool` 池满立即抛 `PoolError`，而工作线程数 40 ≫ 池容量，瞬时并发会直接 5xx）；连接级错误（`OperationalError`/`InterfaceError`）`putconn(close=True)` 丢弃失效连接。验收：`tests/test_record_store_pool.py` **5 passed**、ruff 0、`local_gate --quick` 9/10；**24 并发 × 2 轮**均 `24×200`（669ms / 861ms）；真实写路径 9 步全过、清理后 63 条（有效 36）/ 0 孤儿版本。证据 `output/ci/server/pool-evidence-ec9d769.txt`。**边界**：进程内池，多 worker 需每 worker 独立池；未做停库自愈演练（preview 与正式共用 PostgreSQL 实例，停库会中断 8770）。
- 2026-11-04 全量 pytest 转绿（`20f54ae`，证据 `output/ci/server/full-gate-959-20261104.log`）：在**独立临时 PG 16 集群**（端口 55435、仅 127.0.0.1、12 位 hex run id、regression 角色带 CREATEDB/CREATEROLE、`rag_chunks` 从旧测试库流式预置并授权）跑当前 develop：**959 passed / 23 skipped / 1 deselected / 0 failed / 0 errors（147.33s）**，内存可用全程 ≥1.0GB。唯一 deselected 是 `test_native_backup::test_integration_native_backup_restore_and_transaction_failure`——它要求 `scripts/native_qa.py` 写 marker 的 owned QA 集群或 Docker CLI，临时集群不满足，**显式排除、未改其断言**；该用例仍以专用 native_qa 隔离门禁覆盖。上一轮同集群一次性库的 947 passed / 7 failed / 5 errors 已按此清零。
- 2026-11-04 修复注入式替身退出回归（`20f54ae`）：`lifespan` 的 `finally` 直接调 `store.close()`，而测试注入的 `_NoopStore` / `ProbeStore` 没有该方法，导致 4 项用例在 TestClient 退出阶段抛 `AttributeError`。抽出 `close_store()` 做 `callable` 判断，真实 `RecordStore` 仍正常释放连接池；新增 1 例回归。本地定向测试 **43 passed**（test_record_store_pool / test_middleware / test_operations_release），ruff 0。
- 2026-11-04 历史产物清理（仓库瘦身，供后续推 Gitee/GitHub）：用 `git filter-repo --invert-paths` 从全部历史移除 **4136 个可重生成产物文件（79.4MB）**——`output/stages/`（阶段源码/数据快照 3888 个）、`output/playwright/`（截图与临时脚本 91 个）、`output/web/` 下的 `collab-round1..5`、`design*`、`*-wheel/`、`wheel-check/`、`package/`、`*-before/` 与散落 `*.png`/`*.whl`。跟踪文件 **4643 → 507**，pack **34.73MB → 19.48MB**；历史中这些路径引用为 0。工作区文件已从清理前副本恢复并加入 `.gitignore`（保留 `output/metrics_*`、`output/v0|v1|v1.5|v2` 报告与 `src/.../planning-mist.png`）。**副作用**：98 个提交哈希全部重写，文档里旧的短哈希（如 `ec9d769`、`cbbdb7e`、`22cf654`）只代表清理前历史；清理前完整历史备份在 `E:\project\agents\_git-history-backup-pre-cleanup.bundle`（36MB，确认无误后可删）。**未做**：不清理 `src/` 内 2.36MB 的 `planning-mist.png`（前端真实资源，需转 webp 才能降体积）。
- 2026-11-04 测试/正式环境隔离（preview 已切换）：8771 从共享身份迁到独立运行时——OS 用户 `shilie_pvapp`（UID 992）、根目录 `/var/lib/shilie-preview/app`、独立 PG 16.15 集群 `shilie-preview-postgres.service`（`shilie_pvdb` UID 993，仅 `127.0.0.1:55433`）与库 `shilie_preview_20261104`。迁移在停写证明后走 `pg_dump -Fc | pg_restore --single-transaction` **不落盘 dump**：两端退出码 0/0、23 表行数+内容 md5 全一致、1011 行、索引 23/约束 45/vector 0.8.7/无序列；旧库 `shilie_preview_20261103`（63/122/819）原样保留。运行角色最小权限（records SELECT/INSERT/UPDATE、versions SELECT/INSERT、rag_chunks SELECT、schema USAGE；无 DELETE/TRUNCATE/CREATE），`WORKSPACE_PROFILE=production`+`SCHEMA_MODE=verify` 启动即通过角色校验。`zzzz-preview-isolation.conf`（sha256 `cb8ac9f6…f9752`）在旧 drop-in 后加载并用空赋值复位 Environment/ExecStart/ReadWritePaths；命名空间内 `/var/lib/shilie`、`/etc/shilie`、`/opt/shilie` 实为空占位、正式 env/私钥/私密文件不可见，pvapp 读写正式文件被拒、用新库密码登录 5432 被拒。受控写入（建/改/软删知识）后新库回到 63/122/819，正式库 15/24/494 与 `private-vault.json` 摘要前后一致；20 路由浏览器 0 异常。**风险**：私密口令按用户选择与旧测试相同（vault 字节一致），复用风险仍在；测试数据源自生产副本，隔离≠匿名化。**回滚**：删除该 drop-in → daemon-reload → restart 即回旧身份/旧库。正式 8770 全程未重启未改配置（PID 225177）。
- 2026-11-04 当前 HEAD 全量 pytest（服务器一次性库，`output/ci/server/full-gate-evidence-20261104.txt`）：在既有 PostgreSQL 建一次性 `regression` 角色/库（结束即删，不碰 `shilie_native_20261027` / `shilie_preview_20261103`），把 `/opt/shilie/preview` 复制到 `/tmp` 跑全量（测试副本把 `encryption.enabled` 改回仓库默认 false，不复制服务器密钥）：**982 收集 / 947 passed / 23 skipped / 7 failed / 5 errors（134s）**。逐条归因：**4 项为本批真实回归（未修）**——`lifespan` 的 `finally` 调 `store.close()`，而测试注入的 `_NoopStore` / `ProbeStore` 没有 `close`，`AttributeError` 发生在 TestClient 退出阶段（仅影响注入式替身；真实 `RecordStore` 有该方法，preview 重启/健康正常）；**8 项为环境前置**——副本缺 `docs/openapi.json`、新库未预置 `rag_chunks`、`test_native_release` 需要 ci_verify 专环境、`test_native_backup`/`test_native_schema` 4 例需要 root 预置受限角色。**不得把这轮写成全量全绿**；既有 926 passed 对应更早 HEAD。下一步：修 4 项 close() 回归并重跑。
- 2026-11-03 本机全量基线：`pytest -q` → **760 passed / 5 skipped / 8 failed / 186 errors**（730s）；失败与错误全部因本机无 PostgreSQL（缺少 `SHILIE_QA_RUN_ID`/`POSTGRES_DB=regression` 前置或连接失败），非代码回归；实库覆盖仍以服务器隔离门禁为准。
- `tools/` 三件（栈解析/协议查询/调试检索）与 MCP `/mcp` Streamable HTTP 端点均已接线
- 配置 14 个 yaml（web/settings/prompts/mcp + 业务线）；测试 **59 文件**（本机收集 937 项，另有 QA 环境门禁）；scripts 含 `local_gate.py`、双环境 `deploy_release.py`、`set_login_password.py`
- **双环境运行**：正式 `shilie.service` :8770 为 v103（release `native-20261103-124220-d131fc7`，111 paths / 145 ops）；测试 `shilie-preview.service` :8771 为 v108（`native-20261103-232849-ec9d769` 的代码，2026-11-04 起已切到**独立运行时**：`shilie_pvapp` UID 992 + `/var/lib/shilie-preview/app` + `127.0.0.1:55433` 上的 `shilie_preview_20261104`），**完全独立 PostgreSQL**（正式 `shilie_native_20261027`@5432 / 测试 `shilie_preview_20261104`@55433；旧测试库 `shilie_preview_20261103` 保留不再对外服务）；部署拓扑、systemd drop-in 与全部踩坑见 `docs/DEPLOYMENT_REALITY.md`

## Execution Plan
严格按顺序执行，单变量迭代，不提前引入额外变量

### V0阶段：文档结构验证与最小切片
- **时长**：20分钟最小验证 / 4小时全量完成
- **语料范围**：仅AIhuoke 14份真实生产文档（保证基线干净）
- **核心任务**：
  1. 单份核心文档解析三级标题结构，验证Python环境与文档结构
  2. 全量文档按二级标题切分，输出标准JSONL，字段：`chunk_id`/`source_file`/`h1`/`h2`/`content`/`meta.status_marker`
  3. 生成10道基础评测题，包含`must_retrieve`客观判定字段
- **交付物**：`corpus.jsonl`、`eval_questions.json`、标题结构验证脚本
- **验收标准**：随机10条chunk内容完整；评测题可客观判定；chunk总数为观察项不设KPI

### V1阶段：纯向量检索基线测试
- **时长**：约12小时
- **语料范围**：仅AIhuoke文档，不引入其他变量
- **核心任务**：
  1. 搭建PostgreSQL+pgvector环境，按配置维度创建数据表
  2. 接入sentence-transformers，加载bge-base-zh-v1.5，完成批量向量化入库
  3. **必做对照实验**：query直接编码 vs query加instruction前缀，量化召回率差异
  4. 跑10道评测题基线，记录top-5召回率，标注失败类型（未召回/排序靠后）
- **交付物**：建表脚本、入库脚本、基线测试报告、失败问题清单
- **验收标准**：可正常入库检索；有明确基线数值与前缀对比数据；失败类型清晰

### V1.5阶段：针对性优化
- **时长**：8-12小时，视失败点而定
- **核心任务**：根据V1失败点对应优化，不堆砌功能
  - 切片粒度问题 → 增加字数兜底拆分，或引入三级标题切片
  - 排序靠后问题 → 接入重排算法，调整top-k值
  - 阈值/幻觉问题 → 实现三层降级机制（高置信直接回答→中置信引用→低置信返回未找到）
- **交付物**：优化后的检索脚本、优化效果对比报告
- **验收标准**：每项优化都有单独前后数据对比，可量化提升幅度
- **实测结果（2026-10-10 完成）**：V1 唯一失败类型为「排序靠后」，按单变量接入 bge-reranker-base 重排（候选池 top-20）：top-5 召回率 90%→100%（+10pp），失败题由 #7 救回 #1、无失守；切片粒度与三层降级无对应失败点，按「不堆砌功能」原则暂不引入；详情见`output/v1.5/v15_optimize_report.md`

### V2阶段：能力扩展与工程化
#### V2-a：补充Python公开文档对照实验（约6小时）
- 补充Python标准库、FastAPI、pgvector公开技术文档
- 对照语料候选（2026-10-10 归档，V2-a 启动时再定是否启用）：`data/raw/aux_docs/knowledge_atguigu_assistant.txt`（尚硅谷 LangChain 教程的 atguigu 客服知识库；合成语料，结构为分节符+问答对）
- 使用同一套切片策略，分别测试两类文档的召回率差异
- 输出对照实验报告，验证切片策略对不同文档结构的适配性

#### V2-b：业务状态感知功能（约3-5小时）
- 实现检索后按`meta.status_marker`降权排序
- 回答中显式标注业务状态（CONFIRMED/待注册/占位/不分配）
- 解决"文档有条目但实际未落地"的真实业务坑

#### V2-c：通用工具集开发（约10小时）
1. 协议查询工具：精准检索协议号、命令定义与参数
2. parse_stacktrace通用异常解析工具：输入异常栈，输出结构化错误类型、可能原因、排查方向
3. 检索调试工具：输入查询，返回命中chunk列表、相似度分数、状态标记

#### V2-d：Agent + MCP（约8小时）
- 基于LangGraph构建状态机：意图识别→工具路由→检索→生成完整链路
- 支持多轮上下文记忆、工具调用异常自动降级回退纯检索
- 按MCP标准封装所有工具与资源，内置基础权限控制

#### V2-e：工程化封装（约4小时）
- FastAPI封装查询接口、MCP端点、管理接口
- Dockerfile + docker-compose一键部署
- 最小CI：依赖检查 + 代码格式检查

## Core Modules Description
### Common 通用基础层
- 配置加载器：支持yaml配置+环境变量覆盖，优先级：`.env` > `settings.yaml`
- 通用工具：文本清洗、格式转换、正则工具
- 全局中间件：结构化日志、LRU缓存、统一异常、链路追踪、接口限流，全链路复用

### RAG核心引擎层
- 数据预处理：支持多级标题解析、自适应切片策略、状态标记提取
- 嵌入模型：bge中文模型封装，内置query侧instruction前缀逻辑
- 向量存储：pgvector客户端封装，维度配置化，支持批量入库与相似度检索
- 检索能力：基础向量检索、重排、状态感知降权、三级降级机制

### Agent编排层
- 基于LangGraph构建状态机，完整实现检索增强Agent闭环
- 意图识别：自动判断问题类型，路由到纯检索或对应工具
- 工具执行：统一调度原子工具，参数校验，调用失败自动降级回退纯检索
- 上下文管理：多轮对话会话记忆，上下文窗口自动管理

### 原子工具集
- 独立的原子能力集合，由Agent层统一调度
- 每个工具单一职责，可独立测试、独立替换
- 全部使用Python实现，无语言绑定

### MCP协议适配层
- 兼容Anthropic MCP标准协议
- 工具适配器：自动将原子工具转换为MCP标准工具
- 资源提供者：文档片段、检索结果作为标准MCP资源暴露
- 权限控制：区分只读工具与管理工具
- 保留独立HTTP接口，不强制依赖MCP，可按需开启

## Code Style
1. **命名规范**
   - 文件名/模块名：snake_case
   - 类名：PascalCase
   - 函数/变量：snake_case
   - 常量：UPPER_SNAKE_CASE
2. **类型注解**：所有公共函数必须添加类型注解
3. **文档字符串**：模块、类、核心函数必须包含docstring，说明功能、参数、返回值
4. **错误处理**：使用自定义异常类，禁止裸except；错误信息清晰，禁止堆栈泄露
5. **配置优先**：所有可变参数从配置读取，禁止魔法数字硬编码
6. **导入规范**：按标准库→第三方库→本地模块顺序导入，禁止循环导入

## Commit & Push Convention
1. 格式：`type(scope): 内容`（Conventional Commits 的中文口径，用户指定）
2. type 取值：`fix` / `feat` / `docs` / `test` / `perf` / `refactor` / `chore` / `ci`
3. scope 用一句话说清受影响的中文模块，例如 `修复备份`、`连接池`、`文档`、`测试环境隔离`、`门禁`
4. 内容动词开头，写“为什么/结果”，禁止 `update files`、`misc` 之类无信息描述
5. 示例：`fix(修复备份): 补齐 bookmark/lesson 校验器`、`perf(连接池): 借满等待与失效连接丢弃`、`docs(文档): 记录 8771 隔离实测与回滚`
6. 一次提交只做一件事；代码与文档分开提交，便于回滚与审读
7. 未配置远端前不猜测推送地址；推送前先确认 `git remote -v` 与目标分支

## Branch & Environment Mapping
1. 仓库 `origin` = `git@gitee.com:luojiee/agents.git`（Gitee 私有仓库，SSH 密钥 `id_ed25519_gitee`）
2. 只维护两个长期分支：`develop`（测试/开发，对应服务器 8771）与 `master`（正式，对应服务器 8770）
3. 日常改动提交到 `develop`；正式晋级必须经用户明确同意，用合并/评审把 `develop` 合入 `master`，不直接在 `master` 上开发
4. 服务器部署以分支为准：8771 取 `develop`，8770 取 `master`；禁止把未验收的提交直接部署到 8770
5. 分支保护、CI 触发与部署密钥属于平台/服务器配置，按需单独授权后设置

## CI/CD
1. **决策（2026-11-04）：暂不接入 Gitee Go 流水线。** 单人开发 + 已有 8771/8770 双环境，门禁本地 15 秒即可跑完（`scripts/ci_gate.py`），流水的唯一增量是“推送时强制自动执行”，边际价值低；Gitee Go 免费额度为单仓库 200 分钟 + 每月 500 分钟，超出按量计费。
2. 保留 `scripts/ci_gate.py`：ruff、静态版本号、OpenAPI 契约、前端接口契约、静态资源引用、纯逻辑 pytest 白名单，**不依赖 PostgreSQL / Docker**，本机实测 `CI_GATE_PASSED`（约 15s）。本地、服务器、未来 runner 均可复用。
3. `.workflow/ci.yml` 作为**未启用模板**保留（不接入不产生费用）：push develop / PR master 触发，走主机组 `shilie-ci`。将来有协作者或需要“合并前必须绿”时再开通，建议只保留 `PR → master` 触发以省额度；Gitee Go 云端 Python 插件最高 3.9，项目要求 3.10+，必须走主机组执行。
4. CD 边界（不因 CI 提案改变）：**不配置自动部署**。`develop` → 8771 人工部署；`master` → 8770 必须在全部功能验收 + 用户明确同意后人工执行。部署 SSH 密钥只放平台 Secrets / 服务器 env，禁止入仓。
5. 本机 `pre-push` 钩子跑全量 pytest，依赖本机 PostgreSQL；无库时先跑 `scripts/ci_gate.py`，再用 `GATE_SKIP=1` 推送并在提交说明注明原因；若启用云端流水线，CI 侧不接受跳过。

## Documentation Sync Convention
1. 每个可验收改动完成的同一轮，更新：`DESIGN.md`（当前态/决策）、`PLAN.md`（断面数字）、`progress.html`（看板）、本文件（长期记忆与踩坑）
2. 证据放 `output/` 并写清路径、命令、退出码、数值；未验证项必须显式标注“未验收”
3. 不用计划、模拟或旧结果替代实测；不改写历史证据，只追加新一轮

## Configuration Management
1. 所有配置集中在`config/`目录下，yaml格式
2. 优先级规则：环境变量 > .env文件 > 配置文件
3. 敏感信息（数据库地址、密钥、API Key等）必须通过环境变量传入，禁止写入配置文件
4. 配置修改无需改动代码，重启服务生效
5. 配置项必须有默认值，避免配置缺失导致崩溃

## Testing Specification
1. 测试框架：pytest
2. 测试结构与主包结构一一对应，保证模块可独立测试
3. 核心模块必须覆盖：数据预处理、嵌入、检索、工具函数
4. 每个阶段完成后必须运行对应测试用例
5. 基准测试结果必须存入`output/`对应阶段目录
6. 测试用例必须包含正常用例与异常用例

## Key Notes
### 关键技术坑点
1. **bge中文模型前缀问题（2026-10-10 V1 实测修正）**：官方称中文非对称检索 query 侧应加`Represent this sentence for searching relevant passages: `前缀（passage侧不加）；但**bge v1.5 系列为「指令无关」训练**，本项目对照实验实测（n=10）：加前缀 top-5 召回率 90%→80%（-10pp），**V1 基线采用「不加前缀」**。原「差异可达十几个百分点」的说法针对 v1/英文模型，勿盲用；详见`output/v1/v1_baseline_report.md`
2. **pgvector维度不可逆**：建表时向量维度固定，更换模型必须重建表重灌数据，因此维度必须抽成配置项
3. **切片策略无通用解**：必须根据目标文档结构调整标题层级和字数兜底，没有一套参数适配所有文档
4. **单变量迭代原则**：每次优化只改一个变量，否则无法归因失败原因
5. **重排的候选池边界（2026-10-10 V1.5 实测）**：CrossEncoder 重排只能对候选池（`retrieval.candidate_k`）内条目重排序，池外锚点无法触及——失败点若在池外，需扩大候选池或从切片/嵌入侧解决；实测候选池 20 + bge-reranker-base 使 top-5 召回率 90%→100%（+10pp，唯一失败题 #7→#1），且重排会改变 top-1 排序，下游生成引用须基于重排结果；详见`output/v1.5/v15_optimize_report.md`
6. **应用层加密的边界（2026-11-03）**：`platform/field_crypto.py` 用 AES-256-GCM 做字段级封装，令牌 `enc:v1:` 绑定 `记录类型|字段名`；仓库 `settings.yaml` 默认 `enabled: false`（本地/CI 无密钥），服务器配置开启。密钥在 release 的 `data/local/encryption.key`，部署脚本从上一 release 继承并在缺失时生成；**密钥丢失=密文永久不可解**，不得用“自动生成新密钥”掩盖丢失。历史/导出/备份读取路径已透明解密。
7. **OCR 是可选能力（2026-11-03）**：RapidOCR + pypdfium2 通过 `pip install -e ".[ocr]"` 安装；未安装时文本版简历不受影响，图片上传明确报错。PDF 文本层低于 `jobs.ocr.min_text_chars` 才回退 OCR，`max_pages` 限制资源占用；结果带 `ocr_used`，不改变“只做文本命中、不认定能力”的口径。

### 平台重构决策记录（2026-10-12，用户拍板）
- **LLM 提供方**：OpenAI 兼容 API（DeepSeek/通义优先），密钥走 .env（LLM_API_KEY / LLM_BASE_URL / LLM_MODEL）；生成/拆分失败一律降级纯检索，系统可用性不以 LLM 为前提
- **向量扫描方式**：Step 0-2 起改精确扫描（不建 IVFFlat，`vector_store.index.type: exact`）；237 条量级 ANN 无收益，单域超 ~1 万条再评估 HNSW/分区索引
- **包名**：Step 0 不改名；推迟到 Step 2 验收通过后做一次独立机械改名（全量回归），或永不改
- **life schema 首轮范围**：storyline + act + node + unlock_rule；daily_* 推迟；locked/available 为派生态不入库；storyline.kind 收敛为 main/side
- **推迟项**：日常打卡、AI 自动拆分归类（依赖 LLM，且必须「建议→人工确认」）、metrics 前端看板、Alembic、middleware 五件套
- **域范围**：首批仅 tech_doc + life_planning；第三域有真实内容再立项
- **Step 0 拆分**：0-1 账本（已完成）→ 0-2 namespace+精确扫描重灌 → 0-3 目录重排（platform/domains）→ 0-4 配置切分；每步独立复现验收（V1 90%、V1.5 100%、Q08 #7→#1）
- **账本 domain 字段**：默认 tech_doc；幂等键扩为 (domain, stage, topic)；导出按「域 · 阶段」分组，CLI 支持 `--domain` 过滤

### 面试叙事原则
1. **真实准确**：不夸大参与度，排障案例明确说明是从团队文档学习，不侵占他人成果
2. **动机坦诚**：项目初衷是验证RAG在技术文档场景的效果，同时练手Python后端开发
3. **数据支撑**：所有优化点都有前后对比数据，结论基于实验而非主观判断
4. **亮点聚焦**：重点讲中文嵌入优化、状态感知设计、对照实验结论这些体现思考的技术点
5. **边界清晰**：明确说明自己做的部分、学习的部分、团队的部分，主动划清界限反而更可信

### 本轮工作台实现（2026-10-12）
- 用户授权直接实现，新增服务器部署要求，采用统一 PostgreSQL，不使用 SQLite。
- 已实现网页知识录入/编辑/历史/回收站；人生主线或支线→阶段→任务/前置依赖；阶段日志、源码快照/diff/预检回滚、数据恢复及导出。
- 前端按 state/api/workspace/ui/preferences/views/dialogs/actions 拆为 15 个模块；API 按知识/规划/历史/阶段/查询/导出分路由；领域与通用持久化分离。
- 规划首轮以完整 JSONB 文档事务保存 storyline/act/node/requires，派生解锁态不入库；关系表规范化待真实查询需求独立迭代。
- 0-2 保留原向量事务迁移，主键为 (namespace,chunk_id)，移除 ANN，237 条与题集不变；90%/80%/100%、Q08 #7→#1 复现。
- 43 条测试、网页保存/恢复/导出、390px 布局、完整数据库隔离恢复已验证；Docker Hub 网络超时，镜像构建尚未验证。
- 首版前端被用户认为 AI 感过重，已改为专业文档/任务界面，去掉装饰与口号。详细设计与反思见 DESIGN.md；功能/部署/回滚说明见 README。
- 后续补充的页面密度滑块、保存/失败/任务反馈已浏览器验证；按钮按下 1px、减少动画、390px 布局通过。DeepSeek 仅负责查找参考网址，提示词在 output/web/deepseek-ui-prompt.md。
- 本机 Docker 从 Codex 直接启动时 Ingest socket 出现 error 1920；改由 Explorer 启动恢复，237 条向量仍在。未操作运行文件或重置数据；后续启动采用此路径，保留一次恢复的实测边界。
