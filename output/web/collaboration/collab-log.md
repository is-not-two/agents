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
- **通用 DAG 工作流**：`domains/workflow_graph.py` + `agent/graph_runner.py`，节点 input/retrieve/tool/agent/merge/approval；保存时校验环、重复 ID、不可达节点、模板路径；运行冻结 Agent 版本、逐节点持久化、人工审批暂停/恢复、子 Agent 运行审计；工作流页支持 JSON DAG 新建、运行与审批。
- **简历模块**：`platform/resume_service.py`，支持 PDF/DOCX/TXT/Markdown（10MB），上传即解析；公开 `resume_version` 只存元数据，解析文本/段落/技能存 `data/local/resumes` 私密目录；提供结构化段落、技能命中、版本 diff、JD 对照（只做文本命中，不认定能力）。求职页支持上传、查看解析与对比。
- **UI/静态版本**：agent-studio、automation-views/actions、jobs 页面更新；静态版本统一 v103（66 处）。
- **验证**：新增纯逻辑测试 31 项（DAG/简历/搜索/HTTP 工具）；隔离 PostgreSQL 集成测试 35 项（DAG/简历/求职）与 Agent 能力/可靠性回归 56 项通过；浏览器验收能力绑定、DAG 运行、真实简历上传、控制台 0 错误（截图 `output/web/preview-v103/`）。
- **部署**：preview `native-20261103-124108-d131fc7`、production `native-20261103-124220-d131fc7`，正式备份 `/var/backups/shilie/deploy-20261103-124231`；正式数据仍 15 条记录 / 494 向量。双环境 venv 安装 `pypdf`、`python-docx`；`/var/lib/shilie/config/agent-tools.yaml` 已同步（备份 `/var/backups/shilie/agent-tools-20261103-122620.yaml`）。
- **边界**：DAG 目前确定性顺序执行（`max_parallel` 预留）；简历扫描件不做 OCR；Bing 为网页解析，供应商反爬/条款需上线前复核；未做多用户隔离。

## Round 12（2026-11-03）：多 Agent 并行调度（DeepSeek-V4.1-Flash 执行）

- 目标：把 DAG 从“一次只推进一个节点”改成“同波次按 `max_parallel` 并发”，并保证节点级失败隔离与并行审批正确。
- **调度语义**：每轮取所有前驱已完成的就绪节点，按“input 优先 + 声明顺序”排序后截取 `max_parallel`（1–4）组成波次；波次内用 `anyio.create_task_group` 并发执行，波次结束后按声明顺序统一合并结果并落盘，避开 `RecordStore` 乐观锁冲突。
- **节点级隔离**：新增 `_run_node`，把 `_execute_node` 的 `DomainError`/`ToolError`/超时（`node_timeout_seconds`）统一收敛为节点失败；同波次其他节点继续完成，不再因单个节点异常取消整批。检索节点的同步 `search.query` 改走 `anyio.to_thread.run_sync`，避免阻塞事件循环。
- **并行审批**：多个 Agent 节点同波次进入待确认时，运行记录新增 `pending_children`；`confirm` 逐个确认子运行，未完成的保留，全部完成后继续驱动。`pending_node`/`pending_child` 仍保留首个待确认，兼容旧前端。
- **其他**：终止节点答案改为结束时按声明顺序汇总（暂停恢复后不会丢失早先完成的终态答案）；`domains/automation.py` 增加 `pending_children` 有界校验；前端运行详情显示并行度与同批待确认节点数。
- **验证**：新增 `tests/test_graph_parallel.py` 7 项（波次重叠、`max_parallel=1` 串行、DomainError/ToolError 隔离、超时隔离、并行审批）；`tests/test_workflow_graph.py` 9 项通过；ruff 0；`check_static_version.py` 66 处统一 v104。集成用例 `test_graph_parallel_branches_complete` 已加入 `test_workflow_graph_api.py`，需隔离 PostgreSQL 门禁执行。
- **静态版本**：v103 → v104（66 处）。
- **边界（明确未做）**：仍是“波次内并发、波次间屏障”，一个慢节点会推迟下一波，未实现跨波次动态补位；`max_retries` 仍未消费；未部署到 8770/8771，服务器仍是 v103 release。

## Round 13（2026-11-03）：OCR 与应用层加密（DeepSeek-V4.1-Flash 执行）

- **OCR**：新增 `platform/ocr_service.py`（RapidOCR + pypdfium2）；简历支持 PNG/JPEG，PDF 文本层低于 `jobs.ocr.min_text_chars` 时自动回退 OCR，`max_pages` 限制页数；依赖缺失时文本版不受影响、图片上传明确报错，响应与私密文档带 `ocr_used`。依赖列为可选 `.[ocr]`。
- **应用层加密**：新增 `platform/field_crypto.py`（AES-256-GCM，密钥来自 `SHILIE_ENCRYPTION_KEY`/密钥文件，令牌 `enc:v1:` 绑定 `记录类型|字段名`）。`RecordStore` 对配置字段透明加解密（`knowledge.content`、`job_lead.jd_text`、`resume_version.file_name`），历史/导出/备份/恢复路径同步解密；`PrivateJson` 支持整文件封装，简历解析文本、求职分析、周报使用同一密钥。仓库默认关闭，服务器配置开启。
- **部署持久化修复**：部署脚本改为继承上一 release 的 `data/local`（此前只复制 skills/exports，简历正文会在每次部署后丢失），并把 `data/local` 整体加入 systemd `ReadWritePaths`；首次部署生成 `encryption.key`（0600），后续继承。
- **配置**：`config/jobs.yaml` 增加 `ocr`；`config/settings.yaml` 增加 `encryption`（默认关闭）；`.env.example` 增加密钥变量。
- **验证**：新增 `tests/test_field_crypto.py` 8 项、`tests/test_resume.py` 3 项 OCR 用例；`tests/test_encryption_store.py` 1 项隔离 PG 集成（待 QA 门禁）；本地 36 项相关测试通过，ruff 0，快速门禁 6/7 通过，静态版本统一 v105。
- **测试环境部署**：`native-20261103-150405-2e625e6`（v105）已上线 8771，健康检查通过，数据 55 条记录 / 494 向量未变；venv 安装 OCR 依赖，实测 `OCR_AVAILABLE=True` 且识别出 `RESUME 2026 PYTHON`；字段加密实测落库为 `enc:v1:`、读取为明文，临时验收记录已清理；密钥指纹在两次部署间一致（继承成功）。清理 v103 之前 10 个 release，磁盘从 3.0G 恢复到 16.9G。正式 8770 仍为 v103，未推送。
- **CI/CD**：新增 `.github/workflows/deploy-preview.yml`（workflow_dispatch，`confirm` 必须为 HEAD，需 secrets `SHILIE_SSH_KEY` / `SHILIE_KNOWN_HOSTS`）；正式环境保持人工确认。
- **边界**：加密暂无密钥轮换与离线恢复演练；OCR 未做版面还原/表格结构化；未部署生产。


## Round 14（2026-11-04）：自主维护 · 工作流策略非法类型崩溃（Codex，已收笔）

- 开工：检查适用 AGENTS、DESIGN、本日志与 slow.on（不存在）；git 起始无差异，存在其他 Codex 进程但无未结束阶段，选独立后端领域校验范围，未覆盖已有改动。额度预检由父运行器负责，未启动 runner/app-server、未自行读取额度。
- 先验收现有链路：`python -m pytest tests/test_graph_parallel.py tests/test_workflow_graph.py -q`：25 passed。继而用隔离内存存储和真实 automation 路由验证合法创建→执行→暂停审批→确认完成→重复确认 409（无真实数据库/模型/外部调用）。
- 可复现缺陷：`on_error=[]`、`retry_on=[{}]`、`join_policy={}` 导致 set 成员判断抛 TypeError，POST 创建和 PUT 更新返回 500。方案比较：全局吞 TypeError 会隐藏程序错误，前端限制可被绕过；采用领域层字符串类型守卫，保留合法配置/默认值/错误文案，非法 JSON 返回 DomainError/400，不是新功能。
- 实际修改：`src/rag_tech_retriever/domains/workflow_graph.py` 三处守卫；新增 `tests/test_workflow_graph_policy_validation.py`（非法 JSON 类型/未知字符串、合法策略/默认值、真实路由创建/更新无写入、审批链与陈旧确认）；`DESIGN.md` 追加决策。未改 UI、主题、规划结构、知识标签规范化或运行器；AI 维护不代表用户独立掌握。
- 验证：新回归在原代码先 1 failed（TypeError）；修复后 `python -m pytest tests/test_workflow_graph_policy_validation.py tests/test_graph_parallel.py tests/test_workflow_graph.py -q`：54 passed；两文件 Ruff `All checks passed!`。错误类型矩阵包括 list/dict/null/bool/number/空串/未知串，拒绝时不修改输入。API 非法创建零记录，非法更新版本/数据不变。
- 事务证据：相同 `probe.py FILE` 输入，BASELINE 三字段均 500、MODIFIED 均 400、独立副本实际运行 ROLLBACK.sh 后均 500，三个阶段均 exit 0、非法写入数均 0，合法审批链均完成且重放 409；恢复 SHA256 与原始文件完全相等，补丁可重建修复文件，工作区保留修复态。
- 回滚编号：`20261104-160722-3f84d8ac`；修改前已保存 338 文件阶段源码快照。四角色在该阶段 `artifacts/MODIFIED_FILE.py`、`DIFF_FILE.patch`、`VERIFICATION.txt`、可执行 `ROLLBACK.sh`，另有原始文件和必要探针；不是新增交接文档。
- 如实记录验证工具问题：初次隔离测试应用少注册 VersionConflict→409 处理器，审批重放断言失败；补齐与主应用一致的映射后重验通过，未误改产品。初始 PowerShell 编码/截断、rg 不在 PATH 与两条探索路径错误均已改用 UTF-8/原生定向发现/实际路径，原错误保留在 VERIFICATION.txt。
- 局限：仅本机隔离路由与纯逻辑验收；未跑全量 pytest、真实 PostgreSQL事务、完整主应用鉴权限流或真实浏览器；其余私密滑块、规划交互、模型连接、知识录入未在本轮宣称通过。未部署、未接触真实个人数据/密钥/口令/账户/额度配置。
- 下一项建议：另轮用隔离数据和真实浏览器回归人生规划「分叉→折叠展开→双击编辑→删除撤销→缩放自动居中」，只修复可复现问题；LEARN-001 继续留给用户，不提供答案。

## Round 15（2026-11-05）：自主维护 · 人生规划隔离回归（Codex，无源码修改）

- 开工核对：读取适用 AGENTS、DESIGN 与本日志；slow.on 不存在。存在其他 Codex 进程；起始已有 workflow_graph.py、策略测试、orbit-webgl.html 与 output 产物等未提交内容，全部保留。本轮承接上一轮建议，仅验收人生规划现有链路；不启动 runner/app-server、不自行读取额度，额度由父运行器负责。
- 实测命令：`python output/playwright/maintenance-planning-20261105/probe.py`，exit 0，最终 **24 项断言通过**。真实 Edge 156.0.4314.58 使用独立浏览器上下文、随机回环端口与 run_id 身份核验；挂载当前工作区前端，调用现有 planning/history 路由和领域校验，底层为合成内存记录及历史替身，未实例化真实 RecordStore 或加载项目 .env。外部请求一律拦截，实际外部请求数 0。
- 已验链路：新建主线→六次新增形成七卡分叉→主线向右/支线向下→双击不折叠且编辑保存成功→单击收起/展开→完成进度 1/7（14%）→删除分支→撤销恢复→140% 缩放后选中节点居中误差小于 2px→刷新保留折叠偏好。390px 无文档横向溢出；页面运行异常 0。截图已打开核对，橙白主题与金色主线连接保持。
- 对抗验证：陈旧版本更新 409、未明确 cascade 的子树删除 400、支线下新增主线 400、外部前置依赖阻断删除预检和删除 400、陈旧撤销 409；逐次比较内存记录和版本历史，拒绝请求均无变化。HTTP 记录实际包含上述 400/409，不将它们误报成运行崩溃。
- 定向单测：`.venv/Scripts/python.exe -m pytest tests/test_story_branches.py tests/test_workspace.py::test_derived_unlocking_and_done_status_are_not_persisted tests/test_workspace.py::test_invalid_dependency_rules_are_rejected -q`，**12 passed in 0.11s**，exit 0；未运行涉及真实数据库的 fixture。
- 结果与局限：本链路未复现需自动修复的崩溃、数据错误或不可用功能，不修改 src/tests/config/DESIGN。390px 截图可见固定顶栏遮住规划标题上缘，作为普通体验建议供用户选择，不自动改布局。未验证真实 PostgreSQL 的事务/重启持久化、完整主应用鉴权限流、线上服务；本轮未覆盖私密滑块、模型连接、知识录入及工作流。未部署、未读写真实个人数据、私密口令、密钥、账户或模型设置；不把 AI 验收描述为用户已独立掌握。
- 证据：`output/playwright/maintenance-planning-20261105/` 下的 `probe.py`、`results.json`、`browser-command.json`、`browser.stdout.txt`、`browser.stderr.txt`、`pytest-command.json`、`pytest.stdout.txt`、`pytest.stderr.txt`、`http.jsonl`、桌面/手机截图及合成状态。工具纠偏：初读编码与截断后改 UTF-8 定向读取；Node Playwright 查找失败（exit 1）且用户缓存读取被拒（exit 1），改用本机已安装的 Python Playwright，未安装依赖或绕过权限；错误 routes/plans.py 路径改为实际 planning.py；Git 的 NUL 排除文件失败（exit 1），改为本轮 output 内空文件后 status 成功（exit 0）。
- 回滚编号：**无**（未修改产品源码，无需创建修复阶段或执行源码回滚）；既有 `20261104-160722-3f84d8ac` 阶段及其四角色原样保留，未重做上一轮修复。检查前后规划相关文件、DESIGN 及既有未提交源码共 11 个文件 SHA256 一致；仅向本日志追加本节并保存隔离验收证据。
- 下一项小练习（供用户亲手完成，未代写）：给 `derive_plan` 的进度口径补参数化边界测试，覆盖空规划、三节点一项完成、全部完成；验收为 0%/33%/100%，并确认原输入不被添加派生字段。只补测试、不改业务规则；LEARN-001 标签中文分隔符规范化仍保留，不提供实现答案。

## Round 16（2026-11-05）：自主维护 · 私密状态失败后的重试恢复（Codex）

- 开工：读取适用 AGENTS、DESIGN 与本日志，slow.on 不存在。发现其他 Codex 进程；保留既有 workflow_graph.py、策略测试、orbit-webgl.html 及 output 未提交内容。只触碰无已有差异的私密前端与既有回归脚本，写入前逐文件核对阶段 SHA256，收尾再核对阶段仅三处源码/设计变动。额度由父运行器负责，未调用 runner/app-server，也未自行读取额度。
- 先验收正常链路：真实 Edge 156.0.4314.58，独立上下文和随机回环端口（run_id 核验），挂载当前前端、合成状态/会话接口和空愿望/日记列表。部分拖动复位、桌面绑定后缩到 390px、87% 不解锁/90% 吸附解锁、纵向位移不离轨、pointercancel 不解锁、Home/End/ArrowRight、锁定及离开重进、会话 503 后重试、缺少口令时本地拦截和聚焦均通过。没有输入任何真实或合成口令，没有加载项目 .env、真实 RecordStore、vault、模型或个人数据。
- 可复现缺陷：首次 `/api/private/status` 503 后 `configured=null`、`probing=true`，界面永久显示“正在检查私密状态”；服务恢复、离开重进也不再检查（状态请求计数 3→3），原版浏览器断言 exit 1。比较每次渲染/定时自动重试与显式重试，选显式重试以免后台循环；这是故障恢复，不扩展新模块。
- 实际变动：`src/rag_tech_retriever/api/static/shilie/private-view.js` 在 `privateView` 未知状态分支显示错误与重试，请求结束释放 `v.probing`，`bindPrivate` 的 `retry-status` 清错后重新检查；`scripts/web_regression.js` 补失败→再次失败→服务恢复后重试的回归；`DESIGN.md` 追加依据。未改变口令/票据/88% 吸附、橙白主题、金色主线或规划结构，未实现 LEARN-001，也不将 AI 工程维护算作用户独立掌握。
- 实际验证：`D:/Miniconda3/python.exe -X utf8 output/playwright/maintenance-private-20261105/probe.py` 工作区 **26 项断言通过，exit 0**；修改副本亦同。包括状态仍失败时只发一次请求、无自动重试循环、未知状态不误开口令设置、恢复后清错并出现滑块、状态重试不解锁也不读取列表。页面异常 0，外部请求 0，390px 无文档横向溢出；已打开失败/恢复截图核对，不借机修改既有视觉。
- 针对性后端兼容验证：`.venv/Scripts/python.exe -m pytest tests/test_private_session.py::test_password_required_after_restart -q --basetemp <本轮 output 内唯一目录>`，**1 passed in 4.14s，exit 0**（用例自有临时 vault/合成口令，不是用户口令）。`node --check` 两个 JS 文件均 exit 0；`scripts/check_static_version.py` 实测 65 处均 v115，exit 0；完整 Docker/PG 回归脚本未运行，不宣称全量通过。
- 回滚编号：`20261105-152902-5ea48a4c`，修改前保留 344 文件阶段源码快照。相同 `node status_probe.cjs FILE` 输入：BASELINE 持续加载、无重试/不恢复；MODIFIED 提供重试并恢复；独立修改副本实际执行 `ROLLBACK.sh` 后再次持续加载/不恢复，三探针均 exit 0，恢复 SHA256 与原始相同。DIFF_FILE 可重建修改副本，工作区已应用验证过的修改态；非本轮已有改动保持原样。
- 四角色已逐一重开：`output/stages/20261105-152902-5ea48a4c/artifacts/MODIFIED_FILE.js`、`DIFF_FILE.patch`、`VERIFICATION.txt`、可执行 `ROLLBACK.sh`；绝对路径/哈希/字节数与字面 stdout/stderr/退出码见工具记录及 VERIFICATION。浏览器输入、结果、HTTP 状态与截图在现有 `output/playwright/maintenance-private-20261105/`，未创建交接文档。
- 工具纠偏与局限：初读 PowerShell 编码/输出截断改 UTF-8 定向读取；首次快照 hash 键用了 POSIX 格式而记录为 Windows 格式，修正后才建立快照/写入。修改副本首跑选到无 Playwright 的 venv（exit 1），改为已安装的系统 Python；默认 pytest 临时目录权限拒绝（exit 1），改工作区唯一 basetemp 后通过。一次批量捕获在单测输出阶段未留下有效结果，未算完成，已显式重跑。均未安装依赖、绕过权限或修改产品来适配工具。
- 边界：私密 UI 使用合成协议接口，不是实际后端加密认证/真实 PostgreSQL/重启持久化验收；单独后端测试仅覆盖已有临时会话用例。未部署、未访问线上服务、未改账户/额度/全局模型、未读取或修改用户私密口令与密钥、未向外部发送消息。未复验人生规划、模型连接、知识录入和工作流，不重复声明旧结果。
- 下一项建议：另轮验收模型连接“加载→未配置提示→临时网络失败→重试保留未保存输入”，使用合成配置与本地协议替身，不修改全局模型、不做付费调用。LEARN-001 标签中文分隔符规范化继续留给用户亲手完成，不提供答案。


## Round 17（2026-11-06）：自主维护 · 模型连接隔离回归（Codex，无源码修改）

- 开工核对：读取适用 AGENTS、DESIGN 和本日志，slow.on 不存在；有其他 Codex/Node 进程，保留既有 DESIGN、web_regression.js、private-view.js、workflow_graph.py、策略测试、orbit-webgl.html 与 output 未提交内容。本轮承接 Round 16 建议，仅验收模型连接，不重做规划/私密修复。额度由父运行器检查，未启动 runner/app-server 或自行读取额度。
- 实测命令：`python -X utf8 output/playwright/maintenance-model-20261106/probe.py`，exit 0，真实 Edge 156.0.4314.58 **27 项断言通过**。采用当前前端、实际 model_connection 路由和 ModelConnection 校验/测试/原子保存逻辑；连接文件仅在本轮 output 的唯一 fixture 目录。未保存时以空配置替身代替环境读取，并把 ConfigLoader.load_default 设为失败哨兵，避免加载项目 .env。模拟供应商只监听同一随机回环端口，使用固定无效合成凭据，run_id 核验实例身份；未实例化真实 RecordStore 或连接数据库。
- 已验链路：未配置提示→空密钥本地拦截→显示/隐藏→双击测试仅一次请求→测试成功不保存→重新加载 503 保留未保存的三个输入→恢复后测试成功→供应商 401/畸形响应给安全错误→保存 503 保留输入→恢复后保存成功、完整端点规范化、密码框清空→空密钥更新保留旧值→测试已保存连接→刷新仅恢复公开元数据。初次读取 503 可手动重载恢复，无自动请求循环；陈旧保存/测试返回 409，配置不变且陈旧测试不访问供应商。
- 对抗与目检：HTTP 实录为 14×200、1×401、2×409、3×503；供应商故意回显合成凭据时前端反馈不回显它。localStorage/sessionStorage 不含合成密钥、未捕获页面异常 0、外部浏览器请求 0；后端供应商地址由测试输入限定到本机回环。390px 无文档横向溢出；已打开手机表单和桌面读取失败截图核对，橙白主题保持。退出后 Get-Process 确认无 Python 测试服务残留。
- 结果：未复现值得自动修复的崩溃、数据错误或不可用功能；**没有修改 src/tests/config/scripts/README/DESIGN**，仅新增 output 隔离证据并追加本节。回归及收尾核对的 **39 个文件**（前端 JS/CSS/index、模型路由/服务、既有未提交源码/设计）SHA256 一致。无新设计决策，无需改 DESIGN。
- 证据：`output/playwright/maintenance-model-20261106/` 下 probe.py、results.json、browser-command.json、字面 browser.stdout.txt/browser.stderr.txt、server.stdout.txt/server.stderr.txt、http.jsonl、前后 SHA256、model-390.png、read-failure.png。均已重开核对。初始大段读取截断后改定向 UTF-8；错误 api.js 路径改实际 data.js。第一次追加日志因 PowerShell→Python 管道默认编码导致本轮中文变问号，重开立即发现，已仅替换本轮追加段，改用 .NET 原生 UTF-8 写入，原日志前 47564 字节校验不变；不把乱码记为交付完成。
- 局限：未运行依赖真实 PostgreSQL 的 test_model_connection.py 或全量 pytest，未验完整主应用鉴权/限流、真实服务商连通性/计费、检索/Agent 消费新连接及服务重启持久化；刷新通过不等于重启通过。不宣称其他重点链路已验收。未部署、未触碰真实个人数据/私密口令/密钥/账户/额度/全局模型，未向外部发消息。
- 回滚编号：**无**（产品源码未变，不创建虚假修复阶段）；已有 20261105-152902-5ea48a4c 和 20261104-160722-3f84d8ac 阶段保持不变，不重复宣称执行了旧回滚。
- 下一项小练习（由用户亲手完成，未代写）：为 normalize_base 补纯函数参数化边界测试，覆盖完整聊天端点、末尾斜线、非法协议、地址携带账号或查询参数；验收为有效地址规范化且二次处理不变、非法地址抛 DomainError，全程不发 HTTP/不读 .env，只补测试不改规则。LEARN-001 中文标签分隔符练习继续保留，不提供实现答案；AI 验收不等于用户独立掌握。下一轮维护可另验知识录入失败重试和版本冲突，仍避开标签规范化。


## Round 18（2026-11-09）：自主维护 · 知识保存错误提示崩溃（Codex）

- 开工核对：读取适用 AGENTS、DESIGN 和本日志，slow.on 不存在；存在其他 Codex/Node 进程，保留全部既有未提交源码与设计。承接 Round 17 建议，仅验收知识录入、失败重试和版本冲突；未启动 runner/app-server，额度交父运行器检查。目标 app.js 原无差异，写入前核对 SHA256；阶段前后源码差异严格为下述三处，其他既有改动不覆盖。
- 先验正常链路：新建 v1 → 编辑 v2 → 刷新读回 → 历史两版，七项断言通过。随后隔离存储返回 503，真实 Edge 157.0.4341.42 复现 `showFormError` 的 `insertBefore` 抛 NotFoundError，原错误无法显示；不是后端保存成功或验收通过。原因是 `.form-actions` 嵌套在 `.drawer-content` 中，不是 form 的直接子节点；409 冲突同样会被此异常中断。
- 方案与实际改动：比较全局吞异常、移动全部表单结构、修正局部插入位置，选第三案。`src/rag_tech_retriever/api/static/shilie/app.js` 的 `showFormError` 改为 `actions.before(node)`，缺少操作区则 `form.append(node)`；新增 `tests/test_form_error_rendering.py` 覆盖嵌套/直接/缺少操作区三种结构及提示/复用/清错；`DESIGN.md` 仅追加依据。没有改后端保存协议、LEARN-001、主题或规划结构，也不将 AI 维护描述为用户已独立掌握。
- 真实浏览器命令：`python -X utf8 output/playwright/maintenance-knowledge-20261109/probe.py`，最终 exit 0，**31 项断言通过**。当前前端 + 实际 knowledge/history 路由和领域校验，存储为带版本检查的合成内存替身；随机回环端口、run_id 校验、独立 Edge 上下文、外部请求阻断；ConfigLoader.load_default/真实 RecordStore 构造设失败哨兵，未加载项目 .env 或连接数据库。
- 实际验证：503 后全部草稿保留、记录/历史不变、提交按钮释放且无自动请求循环；手动重试双击只写一次；另一客户端写新版后 409 保留草稿和服务端状态，“保留当前输入”回到编辑表单，“加载最新版本”后可重新编辑；空白/超长标题与非文本正文 400、非法版本 422，均无记录或历史变化；HTML-like 正文以文本呈现、搜索可用。390px 实际点击保存经历 503 → 草稿保留 → 手动重试成功（v4），错误/按钮可见且无文档横向溢出。页面未捕获异常 0、外部请求 0；已打开桌面和手机错误/冲突/编辑截图目检，橙白方向保持。
- 定向检查：`.venv/Scripts/python.exe -X utf8 -m pytest tests/test_form_error_rendering.py tests/test_frontend_contract.py -q --basetemp output/playwright/maintenance-knowledge-20261109/pytest-final-tmp`，**6 passed in 0.13s，exit 0**；Ruff 新测试、`node --check .../app.js`、`scripts/check_static_version.py` 均 exit 0，65 处引用仍为 v115。未跑全量 pytest/完整 web_regression，也未验其他四条重点链路。
- 回滚编号：`20261109-092903-9477df19`，修改前 344 文件源码快照保留。相同 `node form_error_probe.cjs FILE`：BASELINE 嵌套结构 NotFoundError/无提示 → MODIFIED 正常提示、更新、清错 → 独立修改副本实际执行 ROLLBACK.sh 后再现 NotFoundError，三次探针 exit 0，回滚 SHA256 与原始相同。DIFF_FILE 用 git apply 在独立目录重建候选且字节一致；工作区仍为修改态。完整阶段三文件回滚预检 can_apply=true，仅预检未应用；ROLLBACK.sh 只恢复指定 app.js 副本，不声称它恢复数据库或全部源码。
- 四角色已逐一重开：`E:\project\agents\rag-tech-doc-retriever\output\stages\20261109-092903-9477df19\artifacts\MODIFIED_FILE.js`、同目录 `DIFF_FILE.patch`、`VERIFICATION.txt`、可执行 `ROLLBACK.sh`。精确绝对路径、哈希、字节数、命令、字面 stdout/stderr/退出码见 VERIFICATION 与 `output/playwright/maintenance-knowledge-20261109/role-manifest.json`；浏览器结果、HTTP、截图与前后 42 文件哈希均在该既有 output 体系内，未创建逐轮交接文档。
- 工具纠偏与边界：初读编码/截断改定向 UTF-8；进程 CIM 被拒后仅看 Get-Process，未擅自终止其他进程；过宽 output 指令发现触及受限历史 tmp 后改精确祖先路径。首个浏览器探针因重复按钮定位与退出清理报错（exit 1），改精确按钮名与保护清理；最终 fixture 已 terminate/wait。Ruff 首次 I001 已修；静态检查捕获曾误把 GBK 按 UTF-8 解码，显式 UTF-8 重跑；系统 Python 无项目包的检查已改用 venv。各失败未冒充通过，原证据及纠偏保留在台账。
- 局限与下一项：未验证真实 PostgreSQL 的版本并发/事务/重启持久化、完整主应用鉴权限流、线上服务，也不复述旧轮私密/规划/模型/工作流结果。未部署、未清库、未读写个人数据/私密口令/真实密钥/账号/额度/全局模型，未对外发消息。建议下轮用隔离数据和真实浏览器验收工作流“执行→人工确认→完成/重复确认拒绝”，只修可复现缺陷；LEARN-001 继续留给用户，不提供实现答案。

## Round 19（2026-11-09）：自主维护 · 工作流审批隔离回归（Codex，无源码修改）

- 开工核对：读取根及祖先适用 AGENTS、DESIGN 和本日志，承接 Round 18 建议，只验收工作流执行与人工确认。不重复修复既有策略类型边界、私密状态重试和知识错误提示。根目录及可访问协作范围未发现 slow.on；扩展扫描遇到 36 个历史 output 临时目录权限拒绝，未绕过权限，不宣称这些目录已检查。存在其他 Codex/Node/Python 进程，原有未提交文件全部保留；本轮证据使用独立 output/playwright/maintenance-workflow-20261109。额度由父运行器负责，未启动 runner/app-server、未自行读取额度。
- 实测命令：`python -X utf8 output/playwright/maintenance-workflow-20261109/probe.py`，exit 0，真实 Edge 157.0.4341.42 **23 项断言通过**。当前工作区前端 + 实际 automation 路由、GraphWorkflowService 及领域校验；存储为带版本检查的合成内存替身，随机回环端口和 run_id 核验、独立浏览器上下文、拦截外部请求。ConfigLoader.load_default、真实 RecordStore 构造、psycopg2.connect 与供应商入口设失败哨兵，没有加载项目 .env、数据库、个人资料或模型连接。
- 已验链路：真实点击创建审批 DAG → 执行 → 审批前暂停且下游未执行 → 批准后 merge 完成 → 重复确认 409 且记录/历史不变；刷新读回配置；确认接口注入 503 后记录与历史不变、按钮恢复、无请求循环，手动双击重试只发一次确认并完成原运行；拒绝后下游不执行，再次批准 409。工作流配置版本冻结、陈旧执行版本 409 不创建运行；approve 字符串/数组及 selected 布尔值均 422 且不修改数据。
- 浏览器与对抗证据：工作流 HTTP 实录 **31×200、1×201、3×409、3×422、1×503**，未把预期拒绝当成崩溃；未捕获页面异常 0、外部浏览器请求 0。390px 真实点击运行列表打开详情，无文档横向溢出；已打开桌面失败提示和手机详情截图目检，未改橙白主题或规划结构。测试服务 terminate/wait 后仅剩开工前两个 Python 进程。
- 定向单测：`.venv/Scripts/python.exe -X utf8 -m pytest tests/test_workflow_graph.py tests/test_workflow_graph_policy_validation.py tests/test_graph_parallel.py -q --basetemp output/playwright/maintenance-workflow-20261109/pytest-tmp`，**54 passed in 4.16s，exit 0**，stderr 空。未运行依赖真实 PostgreSQL 的 API 集成测试或全量 pytest，不宣称数据库事务/真实并发/重启持久化、完整主应用鉴权限流、线上服务及其他重点链路已验收。
- 结果：未复现需自动修复的崩溃、数据错误或不可用功能，**没有修改 src/tests/scripts/config/README/DESIGN**。检查前后 **351 个源码/配置/文档文件 SHA256 一致**，既有未提交改动保持不变；没有新设计决策。仅保存隔离验收证据并追加本节。回滚编号：**无**（无产品修改，不创建虚假修复阶段）；已有阶段与四角色不改动、不重复宣称执行旧回滚。
- 证据均已重开：上述 output 目录的 probe.py、results.json、browser/pytest-command.json、对应字面 stdout/stderr、http.jsonl、source-before/after.json、closeout.json、approval-failure.png、runs-390.png。初读大输出截断后改定向 UTF-8；探索时猜错 workflows.js/workflow-view.js/test_graph_reliability.py 路径，改用磁盘实际 automation-actions.js/automation-views.js/test_graph_parallel.py，未据此改产品。npx 可用、未找到全局 playwright-cli，沿用既有 Python Playwright 驱动真实 Edge，未安装依赖。
- 仅列体验建议，不自动修改：DAG 审批复用了“待确认入库”标记，拒绝后的 toast 仍写“工作流已继续”；手机固定顶栏遮挡标题上缘，与既有规划检查相似。功能状态及下游阻断已实测，文案/布局调整留用户选择。
- 下一项小练习（用户亲手完成，未代写）：给现有 ConfirmInput 补纯校验参数化测试，覆盖 approve 的布尔值与字符串/数字/数组、selected 中的布尔值；验收为仅接受约定类型、错误输入得到校验异常，全程不读配置、不连接数据库或发 HTTP，只补测试不改协议。LEARN-001 中文标签分隔符规范化继续保留，不提供答案，也不将 AI 工程验收算作用户独立掌握。后续维护可另验审批弹窗“取消”及陈旧待确认版本，不扩展新模块。
- 边界：未部署发布、未清空数据库、未读写真实私密口令或密钥、未改账户/额度/全局模型，未对外发消息。
