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
- `src/rag_tech_retriever/platform/`（27 模块：record_store/private_store/search_service/agent_capabilities/web_search/http_tools/resume_service 等）与 `domains/`（10 模块纯校验层）为现行核心，未在上方树中；`agent/` 现为 capability_runtime/graph_runner/collaboration/evaluation 等 12 模块
- `api/routes/` **21 个路由模块**（OpenAPI 实测 **114 paths / 149 operations**，含检索评测 `/api/eval/*` 与能力目录）；前端 `api/static/shilie/` **28 个 JS 模块，静态版本 v108**（含 evaluation.js、company-capabilities.js）
- 2026-11-03 企业级补强（已提交 `6c973ed`，已部署测试环境，正式未动）：图工作流消费 `max_retries`，支持节点级 `retry`（仅 timeout/tool_error）、`timeout_s`、`on_error=fail|continue|fallback`、`join_policy=any_success`、跨波次动态补位、`node_attempts` 审计；`POST /api/workflow-runs/{id}/resume` 仅恢复只读节点，Agent 节点拒绝自动恢复。前端知识搜索 120ms 防抖 + `#knowledge-panel` 局部渲染、409 冲突对话框、相关笔记；`/api/query`、`/api/knowledge`、`/api/jobs` 增加 response_model；`/api/status` 与 `/api/admin/stats` 改用计数查询。本机纯逻辑测试 29 项通过（DAG 14、契约 4、其余既有），全量 800+ 未跑（缺隔离 PG）；preview 健康、数据基线、OpenAPI 契约已真实 HTTP 复核；登录后交互由 2026-11-03 后续轮次补充验收。
- 2026-11-03 批次 D 后端收口：`/api/status` 的 node/done 计数改 JSONB 聚合（`RecordStore.plan_stats`，新增与内存统计的口径对照测试）；`protect` 请求体限长改按块计数（`api/request_guard.py`，已知超限不读正文、chunked 也不整包缓存，下游解析不受影响）；鉴权抽到 `api/auth.py`（`Authenticator` + 会话签发/校验，规则不变）。新增纯逻辑测试 9 项（鉴权 5、限长 4），本机 42 项纯逻辑 + ruff 全过。
- 2026-11-03 前端批次 B+C（v107，已部署测试环境）：断点收敛为 639/1279/1280（保留 <960 环轨与 <420 漏斗子断点），S 档底部主导航（aria-current）、44px 触摸目标、安全区留白；首屏骨架屏；`back()` 改 `BACK_ROUTES` 回退表。Playwright 对预览做 7 宽度 × 2 页面矩阵：零横向溢出、导航仅在 <640 显示、零控制台错误，回退表落到 `#category/workspace`；截图在 `output/web/preview-v107/`。登录后真实交互仍需账号复验。
- 2026-11-03 门禁补强（`3bc86c0`，已部署 preview `native-20261103-205133-3bc86c0`）：OpenAPI 契约漂移检查进入 `release_gate.py` quick/full 与 `local_gate.py` 阻塞链（此前只有独立脚本），门禁单元测试钉住「命令在链上 + 漂移即阻断」；本机 `release_gate --checks quick` GATE_PASS，服务器 release 内契约 `paths=114` 稳定、门禁测试 8 passed。顺带修复 `local_gate.py --report` 相对路径 `ValueError`。服务器隔离全量 926 passed 证据仍对应前一 HEAD，本轮未重跑。最新 HEAD 已在 preview 真实验证登录与检索：`POST /api/session` 200 authenticated、`GET /api/knowledge` 200、`POST /api/query`（text）200 `engine=全文匹配`；真实 Edge/Playwright 经 SSH 转发验收账号模式登录 → `#home` 渲染、零控制台错误（截图 `output/ci/server/preview-login-home.png`）。真实读写闭环（`output/ci/server/verify_preview_flows.py`）：新建知识 201(v1)→列表可见→更新 200(v2)→历史 2 版→文本检索 200(7 hits)→软删除 200→回收站可见，验收记录随后物理清理，preview 恢复 55 条记录 / 0 知识 / 0 版本；更深层模块交互（求职/规划/备份页面）仍待逐页验证。逐页渲染验收（`output/ci/server/verify_preview_pages.mjs`）：登录后遍历 20 个路由，0 页异常、0 控制台错误，截图在 `output/ci/server/pages/`。收藏/求职/规划写操作闭环（`output/ci/server/verify_preview_features.py`，16 步全过）后按 id 物理清理，preview 回到 55 条记录 / 0 孤儿版本。
- 2026-11-03 备份恢复补齐收藏/谨记（`b9d9ad4`，已部署 preview `native-20261103-214813-b9d9ad4`）：`validate_snapshot` 曾缺 `bookmark`/`lesson` 校验器——导出可以包含这两类，导入预览/恢复却整包 400，用户建过收藏或谨记后无法恢复备份。现把校验器抽为 `SNAPSHOT_VALIDATORS` 并补齐两类，新增 3 例回归（注册表覆盖、两类可恢复、未注册类型仍拒绝）；`ruff` 全过、`local_gate --quick` 7/8 PASS（pytest 按 quick 跳过）。部署前清理 10 个当日旧 release（磁盘 1.6G→19G），部署后健康 ok、55 条记录 / 819 条向量未变。深层模块写操作闭环（`output/ci/server/verify_preview_modules.py`）：谨记建/改；复习卡建→评分 3→历史 1 条→同 `request_id` 重放返回 `replayed`；岗位→投递→PATCH 推进 `interviewing`→面试复盘→按薄弱点建卡；通知摘要预览→入队→取消；导出 JSON→导入选项→导入预览 200 且含 `snapshot_hash`；阶段列表/汇总只读（preview 无阶段）、私密状态只读（已配置）。全部通过后按 kind 物理清理 22 条记录 / 32 版本并删除 4 个验收导出文件，preview 回到 **55 条（28 有效）/ 102 版本 / 0 孤儿**。
- 2026-11-03 本机全量基线：`pytest -q` → **760 passed / 5 skipped / 8 failed / 186 errors**（730s）；失败与错误全部因本机无 PostgreSQL（缺少 `SHILIE_QA_RUN_ID`/`POSTGRES_DB=regression` 前置或连接失败），非代码回归；实库覆盖仍以服务器隔离门禁为准。
- `tools/` 三件（栈解析/协议查询/调试检索）与 MCP `/mcp` Streamable HTTP 端点均已接线
- 配置 14 个 yaml（web/settings/prompts/mcp + 业务线）；测试 **59 文件**（本机收集 937 项，另有 QA 环境门禁）；scripts 含 `local_gate.py`、双环境 `deploy_release.py`、`set_login_password.py`
- **双环境运行**：正式 `shilie.service` :8770 为 v103（release `native-20261103-124220-d131fc7`，111 paths / 145 ops）、测试 `shilie-preview.service` :8771 为 v108（`native-20261103-214813-b9d9ad4`，2026-11-03 批次 D + 前端 B/C + 门禁补强 + 备份校验器补齐部署），**各自独立 PostgreSQL**（正式 `shilie_native_20261027` / 测试 `shilie_preview_20261103`）；部署拓扑、systemd drop-in 与全部踩坑见 `docs/DEPLOYMENT_REALITY.md`

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
