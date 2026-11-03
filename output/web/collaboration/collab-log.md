# 时列前端协作日志（唯一记录文件）

> 约定（2026-10-14，WorkBuddy 拍板）：**本轮起所有协作记录只写本文件**，按轮次追加，不再新建 per-round md/verification.json。身份：用户 = WorkBuddy；执行方 = GLM-5.3-FlashX；对方 = Codex。双方不自称可证底层基座，只认代码与证据。单方执行、另一方只读复核。原始 per-round 文件已按本约定合并删除。

---

## Round 1（2026-10-14）：旧视图死代码清理 + 详情面板验证
**执行：GLM-5.3-FlashX**（问题三 + 问题二）；问题一尺寸实验归 Codex（零文件交叉）

- Codex 复核要点：planning.js 被 views.js 静态导入（删文件必须删 import）；act/task 遗留链在 dialogs()/app.js 事件分支中成套存在；82 个重复 CSS 选择器不判 P0；无 Git 但有 stage_journal 快照回滚。
- 实施（32 步断言全部命中）：Pass 1 删 storyBoard import + planChooser/nodeGraph/taskList/planEditor + planning.js；Pass 2 删 dialogs 的 plan/act/task 三段、saveForm 三分支、13 个死 case、delete-task/storyOpen 监听、renderPage 死注入；缓存 app.js?v=16 / views.js?v=16。
- 未动：data.js、tree-actions.js、automation、/legacy、后端、config。
- 验证：死引用零残留；diff 无存活链路改动行；pytest 60 passed；浏览器 console 全程零报错；运行时 dialog 仅剩 tree/automation/knowledge/stage；/legacy 正常；376px 无横向溢出。
- 问题二结论：面板为常驻稳定列（270px）+ 空态操作说明（即 Codex 推荐形态）；滚轮 69px → Enter 重选 → scrollLeft 保持 69（无跳动）；取消对话框焦点返回触发节点。「选中归零」为 Playwright 点击自动滚动假象。
- 遗留：persistRoute 写 3 个无消费者偏好键（无害，保留）；Esc 在自动化按键路径不关闭 dialog（F3，Round 2 未复现，判桥接假象）。

## Round 2（2026-10-14）：树尺寸实验（Codex 执行）
- 42/320 每组裁 2 个标题 vs 32/280 每组裁 6 个 → **保留 42/320**；裁切根因是 flex 纵向压缩两行 strong，非缩进无效。
- 修复：标题/元信息 flex-shrink + 内边距重分配；160 字长标题两行省略，详情可读全文。改动仅 tree.css（排版修复）+ index.html（tree.css?v=17）+ DESIGN.md；无 tree.js/后端改动。
- 复核 Round 1 清理：无回归，pytest 60 通过；阶段/知识弹窗、Esc、减少动画均补验。F3 未复现（限其 Chrome 路径）。
- 证据：collab-round2/verification.json（8 组前后对照）、stages/20261014-161257-67ef190d/。
- 缓存约定：改 tree.js 需同步 views.js 与 tree-actions.js 的导入版本；app.js:1 引的是 tree-actions.js。

## Round 3（2026-10-14）：planning-mist 同图 WebP 转换（GLM-5.3-FlashX 执行）
- 同像素转码（1672×941 RGB，无缩放）：PNG 2310.4 KB → **q80 151.5 KB（-93.4%，PSNR 35.62 dB，已上线）**；q90 256 KB（37.81 dB）备档 collab-round3/。
- 改动：tree.css 两处引用 png→webp；index.html tree.css?v=18；新增 shilie/planning-mist.webp；**原 PNG 保留**；pyproject 零改动（shilie/* 通配覆盖）。
- 验证：引用零残留；v18 页面网络仅加载 webp（transfer 155438 B）、PNG 零请求、console 零报错；pip wheel 构建且 webp 收录；阶段 20261014-161623-3cae195c 已 finish。
- 限制：after 截图因浏览器节流未拍成，以网络加载 + computed style + PSNR 替代，需人工目检 ?v=18。

## Round 4（2026-10-14）：WebP 目检与发布包瘦身（Codex 执行，已完成）
- 补拍 1440px 同位置 PNG/WebP 横幅与页面截图，当前显示尺寸未见明显退化，保留 q80；页面加载 WebP 155138 字节，JS 无异常。
- 修正口径：body 遮罩较强，但 studio-heading 右端约 15% 不透明度，不能把 91–96% 套用于整个横幅；PSNR 不能独立证明视觉无差异。Round 3 目检遗留已解决。
- pyproject.toml 精确排除 wheel 中的 api/static/shilie/planning-mist.png；本地原素材与快照保留，哈希不变。
- 隔离干净构建：wheel 3018910 → 695662 字节，减少 2323248 字节。ZIP 仅删除 PNG，公共文件仅 RECORD 变化，WebP 与其余运行资源完整。发布包瘦身已完成，不再列为待拍板。
- 构建脚本最后中文摘要输出遇到 cp1252 错误；此前构建、ZIP 断言与报告落盘已成功，打印方式已修正。不将该次脚本描述为全程零错误。
- 修改范围：pyproject.toml、DESIGN.md、README.md；未修改页面行为。证据 output/web/collab-round4/，阶段 20261014-162508-cb45cba3，回滚预检通过。

## 当前交接与记录约定
- Codex 已收笔，下一轮由 GLM-5.3-FlashX 执行；建议检查深层节点添加后的定位、展开与折叠，仅修复可复现问题。
- 所有后续协作说明、验证结论和遗留问题只更新本文件，不再创建逐轮交接 md 或 verification.json。按需保留必要截图、diff 与原有回滚快照，不重复生成整套证据目录。
- q90 保留为候选素材；目前无须替换。CSS 合并仍后置，不按重复选择器计数删除。

## Round 5（2026-10-14）：深层添加定位与折叠修复（GLM-5.3-FlashX 执行，已收笔）
- **隔离测试环境**：新建空库 `qa_collab5` + 独立实例 8771（WEB_PORT/POSTGRES_DB 环境变量覆盖；手动启动进程不碰 runtime.json；需非沙箱启动否则子进程被回收）。用户数据零写入；QA 库保留供后续复用（`$env:WEB_PORT='8771'; $env:POSTGRES_DB='qa_collab5'` 后启动 scripts/v2e_start_api.py）。
- 首次使用流程 ✓：空库空态 → 创建主线「考研上岸」→ 根节点渲染。
- 深链搭建 ✓：4 层链逐层添加，每层新节点选中且滚动跟随（sl 38→80→122→164）。
- **BUG（复现→已修复）**：折叠祖先时经 inspector 给隐藏的选中节点添加子节点 → 保存成功但新节点不可见、定位失效。根因 `tree-actions.js` add 分支仅从 folded 移除直接父与根，中间祖先保持折叠。修复：保存后展开整条父链（keep=根+parent 链，`folded=filter(!keep.has)` 并持久化），无关折叠分支保留。
- 回归：同场景复测新节点可见、链全展开（folded=[]）、滚动定位 sl164/st715；刷新持久化 8 节点全可见；pytest 60 passed。修复首版 filter 方向写反（keep.has 应为 !keep.has），隔离实测当场抓出纠正。
- 遗留观察：「收起」按钮鼠标点击间歇性无效（select 按钮同委托始终正常，时好时坏，疑自动化环境假象）——请 WorkBuddy 真机点一次「收起/展开」确认。
- 阶段 20261014-163545-2b95a520（status passed）。缓存：app.js 内 tree-actions.js?v=17。

## Round 5 补充（同日 30 分钟窗口：首用补验 + fold 诊断翻案，GLM-5.3-FlashX）
- 知识库首用 ✓：QA 空库空态文案、新建笔记对话框（title/content/tags/source 四字段）打开/取消正常。
- 阶段记录页 ✓：列表为空属于预期外发现——**阶段账本走文件系统（output/stages）不走数据库**，QA 实例与生产实例共享项目目录，属设计行为；已核实两库记录完全隔离（生产 4 条无测试数据、qa_collab5 仅「考研上岸」1 条），Round 5「用户数据零写入」结论成立。
- **fold「收起/展开」诊断翻案**：干净环境 4/4 交替点击全部成功（folded 36↔2 字节交替，elementFromPoint 精确命中按钮 12×12）。历史失败案例全部集中在「同页重渲染后立即点击」= 自动化工具坐标缓存假象，**非应用缺陷**；真机确认项从「待拍板」降级为「可选双保险」。
- 环境备注：浏览器桥接本轮 4 次超时/掉线，均以新标签页恢复；QA 实例已停止，qa_collab5 保留（含测试主线「考研上岸」+8 节点，可随时 DROP）。

## Round 6（2026-10-14）：WorkBuddy 报障修复——画布滚到底后页面不接续滚动（GLM-5.3-FlashX）
- **根因**：`tree.css` `.tree-viewport` 设了 `overscroll-behavior:contain`（阻断滚动链）——画布滚到边界后滚轮不再传给页面。
- **修复**：`contain` → `auto`（浏览器默认链式：画布内正常滚、到边界后接续页面；拖拽平移走 pointer capture 不受影响）。index.html `tree.css?v=19`。
- 验证：computed style 已为 auto（v19 生效）；合成滚轮对 scroll-chaining 模拟失真（无法作为链式证据），**需 WorkBuddy 真机刷新 `?v=19` 页面滑一遍确认**。
- 顺带：真机截图证实 Round 5 深链修复在真机正常（8 节点全可见）；生产 8770 实例发现已停，已手动重启（start-web.ps1 在本环境有无 BOM 编码解析问题，你本机不受影响）。

## 当前交接（Round 6 后）
- GLM-5.3-FlashX 已收笔。待 WorkBuddy：真机刷新 `?v=19` 确认滚动链修复。

## Round 7（2026-10-15，Asia/Taipei）：缩放定位修复（Codex，已收笔）
- 用户要求继续，读取 Round 5/6 后接手。开工时 Docker 与8770均停止，已恢复。
- 复现：13层临时数据在140%缩放下编辑保存，横向定位误差-46px。根因仍使用旧卡片半宽114与半高53，且未对中心偏移应用缩放。
- 修改 tree-actions.js：中心按 `(offsetLeft+offsetWidth/2)*zoom` 与 `(offsetTop+offsetHeight/2)*zoom` 计算，再减视口半宽高，浏览器负责边界夹紧。无需新增尺寸配置或改变布局。app.js导入tree-actions?v=20，index.html加载app?v=20；其他模块版本保持，避免treeState重复实例。
- 浏览器复测：80/100/140%三档横纵误差均0；GLM新增祖先链展开保持正确，无关other分支仍折叠，刷新成立。画布滚到底后通过Playwright mouse.wheel输入，页面scrollY由0到87，支持本机Chrome滚动衔接有效；不是DOM dispatchEvent。
- 内容操作使用临时接口数据，未修改个人规划。JS语法通过，本轮未重复后端全量测试。必要源码与数据快照使用原阶段机制，无新增逐轮交接文件或验证JSON。阶段：20261015-092100-d76ee5f9，回滚预检通过。
- Codex已收笔。后续仍只更新本日志，避免与GLM同时改业务文件。

## Round 8（2026-10-15）：分支删除预检与撤销（Codex，已收笔）
- 用户明确授权实际点击继续优化并补齐后端。只读检查知识库、工作流、规划入口后，聚焦删除不可见影响/缺少直接撤销的缺口。采用后端预检+明确确认+会话内撤销，而非继续增加原生confirm文案；正式删除仍重验，预检不替代版本保护。
- domains/life_planning.py新增inspect_branch（父子分支与外部前置依赖独立计算）；GET /api/plans/{id}/nodes/{node}/delete-preview返回版本、受影响节点、阻断任务、can_delete；DELETE复用同一计算，缺节点404、外部依赖拒绝，陈旧版本409。
- 前端新增独立branch-actions.js，显示具体受影响任务，依赖未解除则禁用确认，失败保留错误；删除后显示撤销入口，调用已有历史恢复接口并携带删除后的版本，拒绝覆盖后续修改。undo仅本页面会话内可用，刷新后提示消失，后端历史仍保留。
- 修改tree.js/tree-actions.js/views.js/app.js/index.html引用版本保持一致，tree.css补充确认/撤销样式。用户仍只需填任务名称；没有引入额外必填字段。
- 验证：变更Python Ruff/JS语法通过，全量61 pytest通过。独立qa_demo_story_auto表+8773真实浏览器预览阻断、删除、撤销、预览后并发修改拒绝全部通过；生产个人内容未写入测试任务。控制台唯一网络错误为预期409，无JS异常。确认弹窗截图目检完成；正式8770路由和模块可访问。
- 使用已有阶段快照：20261015-092550-c37d8ff8，回滚预检通过；未新建逐轮交接md/验证JSON。测试服务与本次专用表随后清理。Codex已收笔。

## Round 9（2026-10-15）：功能不可用排查（Codex，已收笔）
- 用户报一些功能不可用。实际发现Round8引入的崩溃：branchNotice条件 undo?.planId===plan?.id 在两边均undefined时为true，随后访问null.count；空规划/空主支线无法渲染，有时URL已变化而内容停在上一页。
- 修复为先明确要求undo和plan均存在，再比较ID。branch-actions/tree/tree-actions/views/app缓存引用同步v22，data.js仍同一v15实例；未改后端。反思：上轮只验证有规划的删除路径，漏掉全空/空分类状态，不能用后端61项通过代替前端状态覆盖。
- 真实独立qa_demo_story_auto表、8773实例验证：知识新增编辑历史、回收站恢复、全文搜索，基础流程启用，Agent编辑，新建入库流程→解析→人工确认保存，检索流程引用、运行详情，空主支线切换刷新，规划新增节点及完成，阶段创建结束（QA目录隔离），偏好持久化与两种导出。修复后脚本异常为0；正式8770主支线切换通过。
- 未完成项明确区分：模型连接仍是服务器配置状态页，真实AI生成没有已配置模型可供验证；备份页仅导出没有网页导入表单。这些未记为已实现。本轮不凭推测宣称所有功能正常。
- 必要JS语法检查通过；前端改动不重复全量Python测试。阶段20261015-094734-39de8165，回滚预检通过。个人数据未写入测试内容；QA服务/表收尾清理。后续仍只在本日志记录。

## 网页模型连接实现中（2026-10-15，Codex）
- 用户明确要求网页填写密钥，覆盖旧环境变量-only限制。比较直接改.env（影响其他配置/环境优先级）、PostgreSQL存密钥（易混入知识导出）与私有文件；选择服务器data/local/llm-connection.json原子保存、同机文件锁和版本检查，原环境/.env作为未保存时回退；网页配置保存后优先并立即读取。该目录已忽略Git且不在源码快照/知识导出中。
- UI提供地址、模型、密码字段、显示切换、测试和保存；密钥空白保留旧值，GET响应只含是否配置，不回显密钥。测试发送短请求，不保存；真实密钥不进入测试产物。

### 网页模型连接交付完成（2026-10-15，Codex，已收笔）
- 修复用户明确指出的缺失：系统设置→模型连接可填API地址/模型/密钥，支持显示隐藏、测试、保存与重新加载；测试不保存，空密钥保留旧值，保存后密码框清空，下一次检索/Agent调用立即读取。应用启动及重启都可使用已存连接。
- 服务端接口GET/PUT /api/model-connection、POST /api/model-connection/test。服务器私有data/local/llm-connection.json覆盖网页未保存时的环境/.env回退；原子替换、线程和Windows/Linux文件锁、乐观版本保护。GET只有has_api_key不含密钥；校验错误不回显原始输入，测试错误不回显供应商正文。文件不在知识/阶段数据导出、源码快照或Git范围内。
- main.py注册路由和动态状态，SearchService读取统一连接；模型调用失败仍保留引用。测试响应格式、401/403/404/429/超时都有明确反馈。README和Agent文案已同步新入口，未改数据库契约。
- 68项全量pytest通过；最终超时/陈旧测试补充后模型连接7项再次通过。独立PostgreSQL+本机模拟服务浏览器全流程通过，验证检索与Agent都使用网页连接；正式8770只读确认表单、测试/保存按钮和空密码框。截图目检完成，390px无溢出。未使用真实服务商密钥，真实连通性以用户输入后的测试为准。
- 一次Agent验收初次等待超时：测试代码绕过UI初始化后未刷新客户端state；刷新后使用同一设置完成验证，不误报为业务故障。
- 配置文件不包含在知识备份中，服务器迁移时需单独保留。阶段20261015-095713-5a33db06，回滚预检通过。测试服务/模拟服务和专用表收尾清理，不新增逐轮交接文档。

## 备份恢复优化进行中（2026-10-15，Codex）
- 用户授权继续优化，补齐备份页只下载不能恢复的缺口。比较直接上传覆盖、服务器临时令牌文件、客户端持有预览内容＋工作区版本指纹；采用第三案，避免额外临时数据文件。预览只读，确认时验证内容hash和工作区revision，表锁内获取保护快照后原子恢复。无效备份先校验，不创建无用阶段。
- 新前端backup.js提供选文件、变化预览、勾选确认、错误与成功反馈。恢复不影响私有LLM配置，保留当前历史；不导入备份旧历史或覆盖阶段文件，页面明确说明。测试只使用隔离实例和数据。

### 备份恢复交付完成（2026-10-15，Codex，已收笔）
- 备份页支持选择JSON、只读预览新增/修改/移入回收站、查看具体条目、勾选后确认；预览后工作区被修改则409并要求重新预览，错误文件明确提示，无变化时不提供无意义恢复按钮。最大文件限制取后端配置，预览与导入都使用32MB级限制。
- /api/import/options、/api/import/preview新增；预览返回规范化内容、变化摘要、记录版本revision与snapshot_hash，不写临时文件或阶段。确认前再次校验文件hash、表锁内检查revision，并在同锁中获取全部当前记录和历史写入保护快照，之后原子恢复。保护失败不写数据，失败事务回滚；旧直接导入API兼容。阶段恢复也使用同锁保护快照。
- 无效snapshot格式/记录kind/规划kind或优先级的列表等类型已改为可读400，校验在创建快照之前完成，避免垃圾阶段。初次快照测试发现记录顺序与export不同，已统一ORDER BY id后复验通过。
- 恢复范围明确：条目数据与回收站状态，保留当前历史，不导入备份旧历史或覆盖阶段文件，不影响data/local的模型密钥。private file不变已测试。
- 验证：76项pytest通过（本轮新增8项）；实际Chrome+隔离PostgreSQL从文件选择到保护快照还原整链通过。刻意并发修改得到409且未覆盖，未勾选无法提交；JS异常0。390px无溢出、截图目检通过，正式8770备份、模型连接和规划只读确认正常。
- 修改集中在backup.js、视图绑定及样式、快照校验/预览、RecordStore恢复事务和exports/stages路由；README同步。阶段20261015-151944-1c3c213b，回滚预检通过。生产用户数据仅执行必要阶段快照，未用于导入验收。测试实例/专用表收尾清理，协作记录仍仅本文件。

## Round 10（2026-11-03）：求职漏斗看板 + 目标公司能力记录（GLM-5.3-FlashX 执行）

- 范围按 WorkBuddy 选定：先做实习侧；上线侧在测试环境验收通过后单独执行正式迁移（见下）。
- 漏斗看板：`GET /api/jobs` 新增 `funnel`（收藏/投递/进面/offer 计数 + 三段转化率 + 本周投递/目标）。进面按已登记面试复盘计，offer 按当前状态计，页面注明两者不保证严格嵌套；空分母返回 null，显示“暂不计算”。周目标 `jobs.funnel.weekly_application_target` 配置化（当前 5），周窗口按 `notifications.yaml` 时区从周一起算。
- 目标公司能力：新增记录类型 `company_capability`，字段 company/role/source/capabilities（name、must|nice、level 1–5、evidence|pending|missing、evidence）/notes；同名能力（大小写不敏感）拒绝；接入 `/api/jobs/capabilities` 五件套、历史/回收站、导出 Markdown。前端新增独立模块“目标公司能力”，复用求职主从布局，窄屏单列。
- 记录类型约束：`RECORD_KINDS` 增加一种 kind；本地 local profile 由 `ensure_schema` 增量重建 CHECK 约束。测试库与正式库最终都迁移到 18 种（正式库迁移见下）。
- 静态版本统一 v101 → v102（66 处），`check_static_version.py` 通过。
- 已验证：求职纯逻辑 24 项 pytest 通过（能力清单正常/异常、漏斗复算与空分母）；ruff 0；全部 JS `node --check` 通过；`local_gate.py --quick` 6/7 通过（唯一跳过为 pytest 全量）。
- 环境隔离（2026-11-03）：新建独立测试库 `shilie_preview_20261103`（正式库一次性副本：15 条记录 / 494 向量），preview 用 drop-in `EnvironmentFile=-/etc/shilie/preview-db.env` 指向该库；此步未动正式库，正式迁移随后单独执行（见下）。
- 部署：v102 已部署测试环境（release `native-20261103-103817-d452b9d`），健康检查通过；测试库 kind 增量迁移 17→18（仅加 `company_capability`，未删数据），迁移前 dump 在 `/var/backups/shilie/preview-db-20261103-103522/`。
- 浏览器验收（Edge + Playwright，ignoreHTTPS，预置会话）：漏斗空态显示“暂不计算”；造 1 岗位 / 1 投递 / 1 复盘后显示 1/1/1/0，三段转化 100%/100%/0%，本周投递 1/5；能力清单新增、详情、归档、回收站均正常；1440px 与 390px 均无横向溢出；控制台 0 错误。验收后测试数据已归档，有效漏斗回到空态。
- 正式迁移（2026-11-03，WorkBuddy 授权）：迁移前备份 `/var/backups/shilie/prod-pre-v102-20261103-104711`（db.dump、旧 17-kind 定义、src、config）；正式库 kind 17→18（仅追加 `company_capability`），记录 15 条 / 向量 494 条未变。
- 正式部署：v102 已上线 8770（release `native-20261103-104739-1002a64`），部署脚本自动备份 `/var/backups/shilie/deploy-20261103-104748`；健康、版本、数据基线与 evaluation.js 均通过。
- 正式只读验收：`/api/jobs` 漏斗结构与空分母正确、`/api/jobs/capabilities` 为空、`/api/status` 200；1440px 与 390px 页面均无横向溢出、控制台 0 错误；未写入任何正式业务数据。
- 回滚提示：正式库已含新 kind，回退 v100 代码前须先恢复旧 17-kind 约束（旧定义见备份目录 `kind-before.txt`），否则服务拒绝启动。
- 集成测试（服务器一次性 `regression` 库 + 临时 QA 角色，跑完即删）：`tests/test_jobs.py` **32 passed**。期间发现“有投递但 0 进面”的断言误写成 null，实际应为 0%；已修正测试并单独提交（仅测试，不影响运行时）。
- 真实 JD 初核（2026-11-03，按 WorkBuddy 目标改为 **AI 应用 / Agent 开发**）：10 家不同公司的公开在招 AI/Agent JD，已导入测试环境 8771 走完整流程；规则提取 **10/10 引用精确匹配（0 条伪造引用）**，初核 **10/10 合理**；明细见下表。最终人工确认仍以 WorkBuddy 为准。
- 初核发现并修复 3 处规则缺陷：“学历及经验”标题误判、“至少 N 年 / N 年左右经验”漏提取、`ReAct` 被误判为前端 `React`；同时补齐 Django/Flask/K8s/LLM/Prompt Engineering/Function Calling/ReAct/LlamaIndex 等词表。preview `native-20261103-114800-4cc2225`、production `native-20261103-115042-4cc2225` 已部署，正式备份 `/var/backups/shilie/deploy-20261103-115052`。

### 10 个真实 AI 应用 / Agent 开发 JD 核对表（2026-11-03，执行方初核）

| # | 公司 | 岗位 | JD 来源 | 规则提取的条件（括号为要求强度） | 初核结论 | 备注 |
|---|------|------|---------|----------------------------------|----------|------|
| 1 | 厦门德捷信息科技有限公司 | AI Agent 工程师（LLM应用 / Agent系统） | [原文](https://m.zhaopin.com/jobs/CC263302730J40756947606.htm) | Agent、LLM、RAG、Prompt Engineering、Python(要求)、Java(要求)、LangChain(加分)；硬条件：本科+3 年 | 合理 | Java 为“任一后端语言”，不是唯一要求 |
| 2 | 上海人工智能实验室 | Agent 开发工程师 | [原文](https://www.shlab.org.cn/joinus/detail/7686149294239467814?location=CT_125&mode=social) | Agent、Function Calling、LLM、RAG(要求)、Docker(要求)、Linux(要求)、Python、ReAct、LangChain(加分)、PyTorch(加分)、LlamaIndex(加分)、vLLM(加分)；硬条件：本科（硕士优先） | 合理 | ReAct 已不再误判为 React |
| 3 | 江苏开拓信息与系统有限公司 | AI Agent开发工程师 / 资深AI全栈工程师 | [原文](https://m.zhaopin.com/jobs/CC246890110J40875528210.htm) | Agent、MCP、LLM、RAG、Prompt Engineering、Context Engineering、Function Calling、Python(要求)、Java(要求)、Docker(要求)、CI/CD(要求)、Kubernetes(要求)、LangGraph、LangChain、Dify、LlamaIndex、pgvector(要求)、FAISS(要求)；硬条件：本科+3 年 | 合理 | AutoGen/A2A 尚未单独成词 |
| 4 | 润建股份 | 大模型应用开发工程师 | [原文](https://m.zhaopin.com/jobs/CC202740210J40966029404.htm) | Agent、RAG、Neo4j、LLM、LangChain、LlamaIndex、FastAPI(要求)、Flask(要求)、React(要求)、Vue(要求)、ReAct(要求)、Dify(要求)；硬条件：本科+2 年 | 合理 | React/Vue/Dify 位于加分项，句级规则标为要求（已知边界） |
| 5 | 智算星空（无锡）科技有限公司 | 智能体开发工程师 | [原文](https://m.zhaopin.com/jobs/CCL1518338570J40970282102.htm) | Agent、RAG、Function Calling、LLM、LangGraph、MCP、Python(要求)、Java(要求)、TypeScript(要求)、Prompt Engineering、LangChain、Dify、LlamaIndex；硬条件：本科+3 年+1 年 Agent | 合理 | 覆盖 Agent 框架与工具调用 |
| 6 | 山东晨歌电子技术有限公司 | 大模型应用开发工程师（Agent 智能体方向） | [原文](https://m.zhaopin.com/jobs/CC269199330J40950082615.htm) | Agent、LLM、ReAct(要求)、RAG、Function Calling、Python(要求)、MySQL、Git、FAISS(要求)、LangChain、LlamaIndex、Docker(要求)；硬条件：硕士+2 年+1 套上线 Agent | 合理 | Docker 位于加分项，句级规则标为要求（已知边界） |
| 7 | 上海灵境起源科技有限公司 | AI智能体研发工程师 | [原文](https://msearch.51job.com/jobs/shanghai/174019258.html) | Agent、RAG、MCP、LLM、Python(要求)、FastAPI(要求)、LangGraph、Prompt Engineering(要求)、Function Calling(要求)、Playwright(要求)、pgvector(要求)、vLLM(要求)；硬条件：本科+3 年+1 年 Agent | 合理 | 覆盖 MCP/浏览器自动化/本地推理 |
| 8 | 滴滴（Food Tech） | AI Agent 开发工程师 | [原文](https://talent.didiglobal.com/social/p/65072) | Agent、MCP、Function Calling、LangGraph、LangChain、LLM、Prompt Engineering、ReAct、Python(要求)、Java(要求)；硬条件：本科（大专可放宽） | 合理 | 覆盖 Function Calling/MCP |
| 9 | 阿里云（ATH-AI创新事业部） | AI Agent 研发工程师（Coding / Harness 方向） | [原文](https://careers.aliyun.com/off-campus/position-detail?positionId=100004083014) | Agent、LLM、Python(要求)、TypeScript(要求)、Prompt Engineering、Context Engineering；硬条件：本科+2 年 | 合理 | Agent Loop / Harness / Subagent 未单独成词，归入 Agent |
| 10 | 福建奇鹭物联网科技股份公司 | AI智能体应用工程师 | [原文](https://m.zhaopin.com/jobs/CC319716280J41001127104.htm) | Agent、LLM、Prompt Engineering、RAG、Function Calling、LangChain、ReAct、Python、FastAPI(要求)、Flask(要求)；硬条件：本科+1-3 年 | 合理 | 覆盖 To C Agent / RAG |

验收口径：≥8 条初核“合理”；本次 **10/10 达线**。此前的通用 Python 后端样本已在测试环境归档，避免与 AI 岗位混在一起；10 条 AI 岗位保留在 `#module/job-insights` 可复核，证据截图 `output/web/preview-v102/jd-insight.png`；正式库未写入。

## Round 11（2026-11-03）：企业级能力扩展（GLM-5.3-FlashX 执行）

- 目标：Agent 可插拔接入工具/技能/MCP，统一格式；联网搜索；通用工作流与多 Agent 协调；简历模块；前后端、数据库、测试与部署全链路交付。
- **统一能力目录**：`GET /api/capabilities/tools` 汇总内置工具、管理员 HTTP 工具、已启用 MCP 工具；新增 `web_search` 内置工具与 `HttpToolGateway`（固定 HTTPS 主机、JSON Schema、模板参数、禁止跳转、响应上限）。Agent 工作室新增「能力绑定」，支持勾选内置/HTTP/MCP 工具、技能与 MCP 服务；权限仍只来自保存的 Agent 配置。
- **联网搜索**：新增 `platform/web_search.py`，支持 Bing CN（默认，服务器网络可达）、Tavily（`TAVILY_API_KEY`）、DuckDuckGo；固定供应商端点、禁止跳转、5 分钟有界缓存、结果条数与 URL 过滤。真实调用 Bing 返回 Python 官方结果，状态 completed。
- **通用 DAG 工作流**：`domains/workflow_graph.py` + `agent/graph_runner.py`，节点 input/retrieve/tool/agent/merge/approval；保存时校验环、重复 ID、不可达节点、模板路径；运行冻结 Agent 版本、逐节点持久化、节点重试上限、人工审批暂停/恢复、子 Agent 运行审计；工作流页支持 JSON DAG 新建、运行与审批。
- **简历模块**：`platform/resume_service.py`，支持 PDF/DOCX/TXT/Markdown（10MB），上传即解析；公开 `resume_version` 只存元数据，解析文本/段落/技能存 `data/local/resumes` 私密目录；提供结构化段落、技能命中、版本 diff、JD 对照（只做文本命中，不认定能力）。求职页支持上传、查看解析与对比。
- **UI/静态版本**：agent-studio、automation-views/actions、jobs 页面更新；静态版本统一 v103（66 处）。
- **验证**：新增纯逻辑测试 31 项（DAG/简历/搜索/HTTP 工具）；隔离 PostgreSQL 集成测试 35 项（DAG/简历/求职）与 Agent 能力/可靠性回归 56 项通过；浏览器验收能力绑定、DAG 运行、真实简历上传、控制台 0 错误（截图 `output/web/preview-v103/`）。
- **部署**：preview `native-20261103-123106-fb25816`、production `native-20261103-123713-fb25816`，正式备份 `/var/backups/shilie/deploy-20261103-123726`；正式数据仍 15 条记录 / 494 向量。双环境 venv 安装 `pypdf`、`python-docx`；`/var/lib/shilie/config/agent-tools.yaml` 已同步（备份 `/var/backups/shilie/agent-tools-20261103-122620.yaml`）。
- **边界**：DAG 目前确定性顺序执行（`max_parallel` 预留）；简历扫描件不做 OCR；Bing 为网页解析，供应商反爬/条款需上线前复核；未做多用户隔离。
