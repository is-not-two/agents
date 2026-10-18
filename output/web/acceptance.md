# 知行工作台交付验收（2026-10-12）

本地运行地址：http://127.0.0.1:8766。正文、人生规划与全部版本统一保存 PostgreSQL，未使用 SQLite。当前应用已通过 start-web.ps1 -Background 启动，停止用 stop-web.ps1；数据库内容保留。

## 实现范围与职责

- 概览：下一步任务、近期知识、真实阶段记录与备份入口。
- 知识库：网页输入标题/正文/标签/来源，保存、编辑、全文检索、历史恢复、回收站。
- 人生规划：主线/支线 → 阶段 → 节点，前置条件、完成/解锁、编辑与版本恢复。循环、自依赖、跨规划依赖、错误完成顺序由服务端拒绝。
- 阶段记录：目标、完成项、问题、验证、文件新增/修改/删除、SHA-256、文本 diff、源码预检、数据恢复、恢复前保护快照。每个阶段有仅依赖标准库的独立源码恢复工具。
- 导出：应用本地留存及浏览器下载 JSON/Markdown；JSON 内容恢复生成新版本。原样迁移全部历史和向量使用 PostgreSQL 完整备份。
- 前端 14 个模块，分 state/API/路由刷新/基础组件/四页视图/领域表单/事件路由。API 按知识、规划、历史、阶段、查询、导出分路由；领域规则与持久化分离。详见 README 职责表。

## 验证与证据

| 项目 | 实测结果 | 证据 |
| --- | --- | --- |
| 测试 | 43 passed；1 项测试客户端弃用提示 | pytest-final.log |
| 真实 PostgreSQL | 重连持久化；两个并发旧版本仅一个成功；软删除/恢复；恢复中冲突时整笔事务回滚 | tests/test_workspace.py、tests/test_web_api.py |
| 源码回滚 | 临时项目实际恢复新增/修改/删除；后续编辑与坏备份拒绝；无应用包时独立工具回滚并二次恢复 | tests/test_common/test_stage_journal.py |
| 域隔离 | 同 ID 跨 tech_doc/life_planning 写入、搜索和计数隔离；未知域为空 | namespace-check.json |
| 精确扫描 | 原 ANN 已移除，真实 EXPLAIN 验证，复合主键正确 | exact-scan-check.json |
| 既有指标 | V1 90%、前缀 80%、V1.5 100%；Q08 #7→#1；逐题结果无变化 | baseline-check.json、v1-recheck.log、v15-recheck.log |
| Web 向量查询 | Q08 真实 Web API 向量+重排 top-1 为评测锚点 | web-vector-check.json |
| 浏览器完整流程 | 网页录入知识/规划，重启后读取，知识编辑/历史恢复，任务锁定→解锁，阶段开始/结束/预检/恢复，JSON 下载 | browser-check.json、../playwright/ |
| 恢复下载内容 | 规划恢复产生版本 7，完成态回到 [true,false]；导出包含 10 个历史版本 | ../playwright/workspace-export.json |
| 响应式 | 1440px 与 390px；四页无横向溢出，最后浏览器控制台 0 errors/0 warnings | ../playwright/*-professional.png、mobile-stages.png |
| 完整数据库恢复 | pg_dump 二进制备份，在隔离数据库 pg_restore 后有 237 条向量；生产库未覆盖 | database-restore-check.json |
| 包与配置 | wheel 成功；独立导入通过；包含 15 个前端模块；RAG_PROJECT_ROOT 支持安装后的配置定位 | package-check.json、package/ |
| 本地应用交付 | 后台启动/停止/再启动实测，health=ok；个人生产记录没有验收样例 | runtime-check.json、runtime.json |
| 交互补充 | 滑块键盘/实时密度/刷新持久/重置；保存冲突保留输入后重试；任务失败恢复、确认后更新进度；检索忙碌态；390px 四页无溢出 | interaction-check.json |
| 最终交互与真实页面 | 按下 1px；真实重载无 JS 错误、无请求失败；未写入个人库；样式版本避免旧缓存 | interaction-closeout.json、../playwright/workspace-final.png、workspace-mobile-final.png |
| Docker 故障恢复 | 直接启动在 Ingest socket 上 error 1920；Explorer 启动后 Engine 29.7.2 可用、PG 健康、237 条向量仍在；未移动或删除 Docker 文件 | docker-recovery-check.json |

切片与题集 SHA-256 与开工前完全一致。量化账本仍为 5 条，不新增未发生的指标提升。

## 限制与未完成项

- Docker Compose 配置检查通过；Docker Hub 鉴权域网络连接超时，镜像未成功构建，容器运行及真实服务器部署尚未验证。源码和部署说明已准备，不能把原生进程验证等同于容器验收。
- 模型 API 未实填密钥，真实生成调用未验证；未配置/异常时页面保留检索引用。个人知识和规划当前使用全文匹配；语义模型用于原技术文档。轻量容器需 WITH_RAG=true 才安装语义依赖。
- 这是共享个人工作区，服务器需访问令牌与 HTTPS；多用户账户/租户隔离、打卡、AI 自动拆分、原规划 Agent/MCP 扩展仍待后续独立阶段。
- JSON 恢复内容保留当前数据库历史，不原样导入 JSON 的旧版本表；跨机器完整迁移使用数据库备份，并迁移阶段/导出目录。
- 代码快照不含 .env、依赖环境与项目根以外的技能；源码与数据库分开恢复，最新阶段预检无冲突时才应用。

## 已发现并修复的问题

1. 单机假设下提出 SQLite，用户补充服务器要求后在实现前改为 PostgreSQL。
2. 第一版页面装饰/口号过多，依用户反馈重做为内容列表、任务层级和阶段时间线；安装并使用 frontend-design 技能。
3. 模块拆分的 async/export 顺序错误由浏览器捕获并修复，最终页面无控制台错误。
4. 快照正文相同但记录类型不同会被跳过，新增反例发现后补齐类型判断，确认后续冲突会撤销整个恢复事务。
5. wheel 安装后原相对包路径会找不到项目配置，补充 RAG_PROJECT_ROOT 并隔离导入验证。
6. 回滚可能删除应用包和回滚 CLI，新增独立恢复工具并真实验证回滚后重新恢复。所有源码修改均有阶段前快照可审查。
7. 交互失败测试使用浏览器拦截的延迟/409/成功响应，不写入个人数据库；真实持久化已在前一轮隔离 PostgreSQL 浏览器验收完成。两类证据分别保留，不将拦截响应当作真实保存。
8. 当前执行环境只读 socket 查询报 error 1920，Explorer 启动同一 Docker 安装可恢复；相关 [Codex 官方仓库问题报告](https://github.com/openai/codex/issues/52698) 提供一致现象。根因仍属推断，本轮未认证所有重启情形。
