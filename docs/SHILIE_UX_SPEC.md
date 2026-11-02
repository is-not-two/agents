# 时列工作台 · 体验设计规范（六节）

> 调研对象：`api/static/shilie/`（19 模块 / 环轨 10 入口）。硬约束：不动后端；环轨内环 6（r=170）外环 4（r=250）；节点无视觉文字；窄屏降级为**内容区 <610px** 时的两列列表（见响应式一节的完整理由）。本文件只写规格，不含实现。
> 已确认裁决：①通知中心=邮件队列，留在设置里并改名「通知与外发」；②到期复习进内环第 5 位；③求职主线合并为 `jobline` 分组；④检索入口统一标注范围；⑤首页两行统计；⑥铃铛+数字徽标；⑦中心胶囊改「N 项待办」；⑧`MODULE_META` 数据表；⑨不引入「已读」语义；⑩周报只上数字摘要条；⑪不预取 jobs/lessons。

## 0. 五个改变方案的调研发现

1. **`notifications` 不是站内收件箱，是 SMTP 外发控制台**（有「确认入队/确认发送/人工核对已收到/取消待发」）。它放在「系统设置」下**是对的**，真正缺的是**接收端** → ① 的答案是「拆」不是「搬」。
2. **`GET /api/notifications/daily-preview` 已是现成的今日摘要端点**：返回 `{date,title,body,counts:{followups,reviews},as_of}`，**只读**（仅读 `learning_card`/`application`）→ 一个端点同时给出**徽标数字**和**摘要正文**，零新增。
3. **Ctrl+K 现在只搜模块名**：`populateQuick()` 只过滤 `modules` 的 title/group，是「模块跳转」不是内容检索 → ④ 的前提需修正。
4. **三套检索里只有一套是真检索**：`documents` 是语义检索；`job-insights` 是对**已记录岗位**逐条对照（输入是岗位下拉，不是关键词）；`workflows` 是配置 → 真正的问题是**四个长得像检索、实际四件事，且没有一处说明各自范围**。
5. **`updatePosition()` 会崩**：`groups.find(g=>g.id===module.group)` 找不到就取 `group.title` → TypeError。**给模块换 group 而不同步加 group，除首页外每页都崩** → 分组改动必须原子发布（见文末批次 1）。
> 另修正 brief 两处与代码不符：环轨节点实际**内 76px / 外 64px**、图标**34px / 29px**（非 16–18px）；节点是**深底球体+金图标**，视觉文字已 `clip-path` 隐藏。
> 端点可达性另有专项审计（13 个真孤儿端点、2 个接错的诊断路径、一整套不可达的 `planning.js`+`chapters.css`），见 `docs/SHILIE_REACHABILITY_AUDIT.md`；本规范受其影响的 3 处已就地标注。

---

## ① 通知中心归类错误

**结论**：拆成两个概念。**顶栏新增「铃铛」= 站内待办入口**（常驻、跨会话）；`notifications` 模块**留在系统设置**并改名「**通知与外发**」，定位为外发投递控制台。铃铛=发现层，「通知与外发」=处置层。
> **命名纪律（避免重蹈「通知中心」这个名的覆辙）**：`notifications` 模块是**每日提醒邮件的发送队列**（配置驱动的发送管理页），它待在「系统设置」下是**合理的**，不是归类错误。真正缺的是**接收端**——一个告诉用户「今天有几件事等我」的常驻入口。所以**铃铛不叫「通知」，叫「待办」**：面板标题用「今日待办」而不是「通知中心」，避免与设置里的「通知与外发」同名同义混淆。

**界面规格**：顶栏 `.top-actions` 最左新增 `<button class="bell">`，铃铛 20px 描边 1.5（`icons.js` 增 `bell` path）；按钮容器 40×40，命中区补足 44×44。**徽标用数字不用红点**——红点在「1 条」和「40 条」时无法区分，会训练用户忽略。点击开**下拉面板**（不跳页，铃铛是「瞄一眼」的面板，跳页制造返回成本）：宽 360px / max-height 420px 内滚 / 右对齐。**面板标题用「今日待办」**（不是「通知中心」）。三段自上而下：①**今日摘要**（`daily-preview.body`，默认折 3 行 + 「展开」）；②**待处理队列**（`failed`/`unknown` 各一条，显示标题 + `last_error` + 「去处理」→ 跳 `#module/notifications`）；③**页脚**「打开通知与外发 →」（→`#module/notifications`）。<960px 变**底部抽屉**（100% 宽 / 70vh）。

**徽标计数（唯一口径）**：**没有 unread/read 字段，也不需要**。
- **徽标数字 = `daily-preview.counts.reviews + counts.followups`**（今天有几件事等我做）。**只含一个端点**（`GET /api/notifications/daily-preview`），boot 期即就位，与行 A 前两格共用同一份快照 → 不会出现「角标说 3、页面说 2」。
- **`failed`/`unknown` 队列数不进徽标**。理由：徽标语义是「今天该做的事」，而投递失败是**运维状态**——它需要去「通知与外发」页做人工核对，在铃铛面板里点一下并不会解决它。混进徽标会让徽标从「今天有 N 件事」退化成「有 N 个问题」，两者不可比。
- **徽标是无状态的**：打开面板**不消数字**，只有问题真被解决（`daily-preview` 的计数下降 / 队列条目被 resolve）数字才降。**不引入「已读」语义**（裁决 8）：与本系统「状态即真相、需人工核对」的哲学冲突，且「已读」与「failed 仍未解决」互相矛盾。
- 若日后确实要「已读」，需新增 `POST /api/notifications/{id}/read` → `{read_at}` —— **不推荐**。

**三个补充定义**

**① 中心胶囊的 `aria-label` 拼装规则**
胶囊视觉文案从「环轨运行中」改成「N 项待办」后，"环轨在转"这个状态就没有文字表达了。视觉上靠 `data-orbit-speed` + 中心脉冲环表达，但读屏用户拿不到。**规则**：
```
aria-label = "进入工作台" + (运行态 ? "，环轨运行中" : "，环轨已暂停") + (N > 0 ? "，今日 " + N + " 项待办" : "")
```
- N = `counts.reviews + counts.followups`，与徽标数字、胶囊视觉文案**完全一致**——**不拆成「3 张卡片 2 个岗位」**，因为胶囊上只显示一个数字，读屏播报两个分项会让听觉信息与视觉对不上。
- 运行态取自 `data-orbit-speed`（`running` / 静止），静止时用「环轨已暂停」。
- N = 0 时省略数字部分，只留「进入工作台，环轨运行中」。

**② 行 A 第三格「通知待处理」跳哪** → **跳铃铛面板（就近）**，与你的倾向一致。
- 依据：待办行的语义是「去做事」，铃铛面板里已能看到失败条目并直接处理，不该再跳一次页。
- **但要分清两层**：铃铛面板是「**看**」，「通知与外发」页是「**做**」。面板里的每条失败项带一个「去处理」按钮 → **跳 `#module/notifications`**（那里才有完整的队列处置 UI：确认入队 / 确认发送 / 逐条核对重试 / 取消待发）。
- 结论：**行 A 第三格 → 铃铛面板；面板里的「去处理」→ 通知与外发页**。这与本节「铃铛=发现层、通知与外发=处置层」的两层结构一致。

**③ 空态的完整定义**
| 场景 | 表现 |
|---|---|
| `counts` 全 0（确实没有待办） | 徽标**不显示数字**，**保留铃铛图标**（用次级色，>0 时用主色 + 数字）——不能因为没有待办就把入口藏了。铃铛面板显示 `daily-preview.body` 全文（它此时是「待跟进 0 条，待复习 0 张」+ 两个空列表）+ 底部「打开通知与外发 →」 |
| `counts` 未知（端点失败） | 徽标**不显示数字**（不是 0）；面板显示「暂时读不到今日摘要」+ **重试按钮** |
| `failed`/`unknown` = 0 | 面板「待处理队列」区显示「没有待处理的投递失败」；该区**始终渲染**（不渲染会造成面板高度跳动） |
| `failed`/`unknown` 未知 | 该区显示「暂时读不到队列状态」+ 重试 |
| 行 A 三格**全为 0** | **保留一行**，显示「今天没有到期的事」+ 次要链接「去复习 →」。**不隐藏整行**——整行消失会造成布局跳动（进入时 3 格、消失时 0 格），而且"今天没有到期的事"本身就是用户来首页要买的确认 |
| 行 A 三格**为 —**（未读到） | **不折叠**，保持 3 格占位。把「没读到」渲染成「今天没有到期的事」是最糟的错误——它会让用户以为今天没事而停下 |

**Toast 与通知的边界**

| | Toast | 铃铛 / 通知 |
|---|---|---|
| 生命周期 | 4.2s 自动消失（沿用 `app.js` 的 `toast()`） | 不自动消失，直到问题被解决 |
| 语义 | 刚做完动作的**瞬时反馈** | 跨会话**未解决状态**，需用户决策 |
| 可回溯 | 否 | 是 |
| 示例 | 「笔记已保存」「已入队，尚未发送」 | 「1 条投递状态未知，需人工核对」 |

**规则**：① 成功且无后续 → 仅 Toast；② 成功但留下未解决状态 → Toast **且**徽标变化；③ 失败/未知 → **只改徽标，不弹 Toast**（Toast 会消失而问题还在，反而制造「已处理」错觉）。

**数据来源**：`GET /api/notifications/daily-preview`（`{date,title,body,counts:{followups,reviews},as_of}`）、`GET /api/notifications`（`{notifications:[],settings:{enabled,configured,delivery_semantics}}`）——均已存在且只读。
**改动文件**：`index.html`（顶栏按钮+面板容器；**顶栏是静态 HTML，不在 `views.js` 里渲染**）、`app.js`（开关/Esc/焦点归还/徽标）、`icons.js`（`bell`）、`app.css`、`learning.js`（模块改名与文案）、`data.js`（`state.digest`/`state.queue`）。

---

## ② 「到期复习」没有入口

**结论**：升到**环轨内环第 5 位**，第一入口级别。**形态分三处，职能不同**：
1. **环轨节点**：内环第 5 位，`icon: task`，标题「到期|复习」（`|` 是既有强制断行约定，见 `views.js` 的 `wrappedTitle`）。**节点上不放数字徽标**——节点是深底球体、环体由 `::before/::after` 画出、直径仅 76px，塞两位数字要么压住环体，要么旋转中读不清。
2. **中心「进入」按钮的副标胶囊**：`.sl-orbit__hub-state`（132px 圆内、10.5px 胶囊）现为「环轨运行中」，改为「**3 项待办**」/「今日无待办」。中心是环轨唯一静止元素，数字放这里一眼可见且不与旋转打架——**把装饰文案换成信息**。
3. **`.home-main` 今日待办格**（见 ⑤）给精确值+文案。

**点进去**：现有 `#module/learning` 页**完全不改**（列表→选中→显示答案→四档自评已实现）。

**未到期数量怎么算**：**唯一来源 = `GET /api/notifications/daily-preview` → `counts.reviews`**（boot 即就位，与徽标、行 A 前两格共用同一份快照）。
- 口径与 `learning/cards` 的 `due_ids.length` **完全一致**（`not paused and due_at <= now`，已逐行核对 `platform/learning.py` 与 `platform/weekly_report.py`）→ **无需新增端点**。
- **首页不必额外请求 `learning/cards`**：`learning.js` 第 26 行已在并行拉 `[api("notifications"), api("notifications/daily-preview")]`，但它按需加载、首页未必拉过——所以 **boot 期由 `data.js` 拉 `daily-preview` 一个端点即可**，它同时给出摘要正文和两个计数。
- `learning/cards` 仍是**复习页自身**的权威数据源（`learning.js` 自持缓存即可），两者口径相同所以数字不会打架；首页不需要它。

**被替换的环位**：内环原第 5 位 `stages 阶段记录` → 退到「个人工作台」分组页（2 步可达）。理由：`stages` 是事后归档日志（频次低），`learning` 是每日动作（频次高），每日摩擦净下降；`stages` 数据与页面完全不动。**备选**：若放宽内环为 7 位（步长 51.43°，r=170 仍容得下）可同时保留 `stages`，默认按 6 位执行。

**数据来源**：首页用 `GET /api/notifications/daily-preview` → `counts.reviews`（见上）；复习页自身用 `GET /api/learning/cards` → `{cards:[],due_ids:[],as_of}`。**注意**：`learning.js` 现自持 `cache.cards`——若首页也去拉同一个端点，会出现两个时间点的快照（角标 3 / 页面 2）。**正确做法是首页不拉 `learning/cards`**，只用 `daily-preview.counts.reviews`，两者口径相同故数字恒等。
**改动文件**：`views.js`（`ORBIT_INNER`）、`orbit.js`（hub 副标）、`data.js`（`load()` 加端点、`state.dueCount`）、`learning.js`（改用共享缓存）、`app.css`。

---

## ③ 求职主线散落

**结论**：**合并为独立分组 `jobline`「求职主线」**，占外环第 1 位。组页本身就是这条流水线。分组 id `jobline`，caption「**投递 → 证据 → 周报 → 复习**」；组内 4 模块按流程排序，组页每项加**步骤徽标**「第 1 步…第 4 步」：

| 步骤 | 模块 id | 标题 | 组页描述（替换现有硬编码三元表达式） |
|---|---|---|---|
| 1 | `jobs` | 求职记录 | 岗位、投递、跟进与面试复盘 |
| 2 | `job-insights` | 岗位证据对照 | 把 JD 缺口和你的实际证据逐条对齐 |
| 3 | `job-weekly` | 求职周报 | 本周投递、面试与进面率的统计快照 |
| 4 | `learning` | 到期复习 | 复盘与 JD 缺口生成的复习卡；手工卡也在此 |

**为什么合并而不是只改导航**：四个名字（求职记录/岗位证据对照/求职周报/到期复习）单独看**看不出先后关系**；合并后组页读作四步流程，「投→记→产→固化」由**位置**承担，不需额外文字解释。**`learning` 放进来的取舍**：复习卡来源有 `manual`/`interview`/`jd_gap`，手工卡严格说不属于求职，但它是这条线的收口动作，**收益大于代价**；描述里写明「手工卡也在此」。**不合并的次选**：四模块在 workspace 内连续排布 + 「第 N 步」前缀 + 连接线——不推荐，侧栏是平铺列表，画连接线要新增结构，且分组页仍看不出流程。

**求职周报是否提升到首页**：**是，但只提升「数字摘要条」，不把 markdown 搬上首页**。取 `GET /api/jobs/report/weekly` 的 `current.metrics`：`applications_submitted`（本周投递）/`interviews_recorded`（本周面试复盘）/`cohort_interview_rate`（投递组累计进面率）/`followups_due`/`reviews_due`，一行 4 个数字 +「查看本周周报 →」。该端点**只读**（`platform/weekly_report.py`：查询不调用模型、不写文件），且 `PrivateJson.read()` 在文件缺失时返回 `{data:null}` 而不抛错 → **新用户首次访问安全**。

**外环新清单（4 位）**：① `jobline` 求职|主线　② `workspace` 个人|工作台　③ `automation` 自动化|中心　④ `private` 私密空间。
**移出外环**：`settings` 系统设置 → **顶栏齿轮按钮**（`#category/settings`）。设置是工具不是工位，放在常转的环上是噪声；齿轮是通用约定、1 步可达。`private` **保留外环并保留虚线描边**（`.sl-orbit__node--private`）：私密空间的「可能被人看见」语义需要独立视觉族，不能因降级到分组页被抹掉。

> **第 1 步可以做得更完整**：后端已有 `GET/POST /api/jobs/applications/{application_id}/reports`（按投递聚合/追加面试复盘）但**前端未接**——现在只有全部复盘的平铺列表。这恰好是「投→记」那一步最自然的交互（在投递详情里直接写复盘）。**这是端点审计里唯一建议与导航重构同期接入的孤儿端点**，接上后第 1 步才算闭环。详见审计文档 1.3。

**改动文件**：`data.js`（`groups` 增 `jobline`；4 模块 `group` 改 `jobline`；`modules` 增可选 `step` 字段）、`views.js`（`ORBIT_OUTER`/`ORBIT_INNER`/`category()`/`sidebar()`）、`app.js`（`updatePosition()` 面包屑）。

---

## ④ 三套检索并存

**结论（前提修正）**：四条「找东西」里**只有 `documents` 是真检索**；`job-insights` 是对照工具、`workflows` 是配置、Ctrl+K 是模块跳转。真正的问题是**没有一处告诉用户各自管什么范围**。对策不是合并页面，而是**统一语义 + 标注范围 + 统一快速查找**。

**统一语义三层（写进文案）**

| 动作词 | 模块 | 副标（范围提示，一行） |
|---|---|---|
| **检索** | documents 技术文档检索 | 范围：技术文档 · 个人知识 · 人生规划 |
| **对照** | job-insights 岗位证据对照 | 范围：仅已记录的岗位与你的证据，不做全文检索 |
| **配置** | workflows 工作流 | 范围：仅工作流配置，不查内容 |

> ⚠️ **范围提示只说「搜哪些内容」，不说「怎么搜」**。原因：`app.js:344` 把 `mode` 硬编码成 `"text"`，`search_service.py:191` 走 `_text_search` —— **当前 `documents` 是全文匹配，不是向量检索**。后端的 `mode:"vector"` 只对 `scope ∈ {all,docs}` 生效，且**只作用于技术文档**，个人知识与人生规划始终是全文匹配（`search_service.py:194`）；向量不可用时自动回退并附 `notes`「向量检索暂不可用，本次已切换全文匹配」（`:209`）。
> 所以：**① 范围提示里不要出现「向量检索」字样**（那是给开发看的，不是当前行为）；② **「用的什么引擎」已经由结果上方的 `result-meta` 运行时显示**（`views.js` 渲染 `searchResult.engine`，值为「全文匹配」或「技术文档：向量 + 重排；个人内容：全文匹配」）——**静态副标只管范围，动态引擎由既有的一行承担，不要重复**。
> **是否接上 `mode:"vector"` 属于行为变更，建议单列批次**，不要夹带在导航重构里。若要接：后端已就绪且会优雅回退，`server-status.js` 已能显示向量库可用/不可用，正好做降级提示。
> 另：`views.js` 里 `scope` 的四个选项（`all/personal/docs/planning`）在 `:295-299` 与 `:324-328` **重复写了两遍**，加提示时顺手提成一个共享常量（后端 `GET /api/query/options` 已返回 catalog 选项）。

范围提示放三处：① 模块页 `h1` 下方一行 `.scope-hint`（13px 次级色）；② 侧栏条目 `title` 属性 + 窄屏列表小字；③ **分组页模块描述统一以「范围：」开头**——把 `views.js` 里那条硬编码三元表达式抽成数据表 `MODULE_META[id]={desc,scope,step}`（顺带承载 ③ 的步骤徽标）。**不推荐**把 `documents` 改名「资料检索」：它的 `scope` 已含 personal/planning，名字确实不准，但改名破坏既有认知，加副标成本为零、收益即时。
> **为什么 `MODULE_META` 比看起来更该做**：现在 `views.js:204` 那条三元表达式**只有 7 个 id 有专属文案**（knowledge / jobs / lessons / planning / stages / workflows / documents），**其余 12 个模块全部落到默认兜底「查看和管理工作区设置」**——job-insights、job-weekly、learning、notifications、agents、agent-studio、collaboration、runs、connections、backup、appearance、private **这 12 个的分组页描述全是错的**（一个岗位对照页显示「查看和管理工作区设置」）。**一次改表即可修正 19 个模块的描述**，成本极低、可见度极高——用户进任何分组页第一眼看到的就是它。
> **`MODULE_META` 表的字段与要求**：`{desc, scope, step}`。`desc` = 分组页上的一行说明（不是副标，副标是模块页的 `scope`）；`scope` = 模块页 `h1` 下的范围提示；`step` = 求职主线分组内的步骤序号（第 1–4 步），其余模块留空。**19 个模块必须全部有 `desc`**，不允许落到兜底文案。
> **「自动化中心」分组的描述文案（中性措辞）**：`范围：工作流配置、Agent 与协作运行记录`。**不要写「Skill 市场与 MCP 服务器管理后端已就绪，界面尚未开放」**——那是给开发看的话，不该出现在用户界面里。后端另有 Skill 与 MCP 服务器管理能力（本轮不接，见审计文档），但界面文案只描述**当前可见的范围**。

**Ctrl+K 覆盖范围 → 升级为统一命令面板**。现状：`populateQuick()`（`app.js:672-682`）只过滤 `modules` 的 `${m.title} ${m.group}`，无去抖，输出只有模块链接。改造为三段结果：**① 跳转**（现有模块过滤 + **补上分组入口**）；**② 笔记**（`state.knowledge` 本地匹配标题/正文/标签，随 boot 已加载，零新增请求）；**③ 全文**（转发 `POST /api/query`，`scope=all`，命中按 `h.category` 分组——`search_service.py` 的 hits 自带 `category` 字段，前端直接可用）。实施约束：输入去抖 **250ms**；**复用 `app.js:310` 已有的 `searchRequestSequence` 取消过期请求**（`:336` 已在用）；面板标题改「**快速找到**」，placeholder 改「搜模块、笔记，或搜技术问题」。**本轮不覆盖**岗位记录/复习卡/谨记——它们按需加载，要覆盖需在 boot 预取 `/api/jobs`、`/api/lessons`，给首屏加 2 个请求，**列为下一轮**。

> **分组入口补的是「标题断层」**：现在 `populateQuick` 匹配的是 `m.group`（**分组 id**，如 `workspace`），不是分组标题（「个人工作台」）——所以**搜「workspace」能搜到模块、搜「个人工作台」搜不到**。补分组条目正好补上这个断层：**每个分组作为一条可点击结果，匹配时同时命中分组 id 与分组标题**。
> 分组数量：**③ 落地后共 5 个**（`workspace` / `automation` / `settings` / `private` + 新增 `jobline`），所以命令面板要补 **5 个分组入口**。批次 1 先落 `jobline`，批次 4 再补面板——**两者有先后依赖，不要倒过来做**。

**要不要统一成一个入口再分结果来源？** **内容检索统一**：Ctrl+K 一个入口、结果按来源分组 —— 是。**场景页面不合并**：`documents` 保留整页，它带 namespace 语料选择、引用列表、AI 回答，是「**深入研究**」的工作台而非搜索框。一句话分工：**Ctrl+K = 快速找到；技术文档检索 = 深入检索**。
> ⚠️ 后端还有第四条真检索 `POST /api/chat`（多轮消息→检索引用+生成）**无任何界面入口**。**本轮明确不接**——在范围标注体系落地前再加一条入口会放大原有问题；日后接入应挂成独立「对话」模块，Ctrl+K 的「全文」段仍走 `POST /api/query`（有引用）。详见审计文档 1.2。

**数据来源**：`POST /api/query`（`{query,scope,mode:"text",generate,namespace}` → `{hits:[{title,content,category,source,status_marker}],answer,engine,notes}`）、`state.knowledge`、现有 `modules`/`groups` 常量 —— **无新增端点**。
**改动文件**：`app.js`（`populateQuick`/`openQuick`）、`index.html`（标题与 placeholder）、`views.js`（`MODULE_META` + `category()` 重写）、`app.css`（结果分组）。

---

## ⑤ 首页统计块重复且缺行动信号

**结论**：改成「**两行统计 + 一行细字链接**」。核心动作是**把行首换成行动信号**，而不是把统计块做得更花。

**行 A · 今日待办**（3 格，视觉最强；`value>0` 时数字用强调色）：**到期复习** = `due_ids.length`，副「张卡片待巩固」，→`#module/learning`；**待跟进岗位** = `metrics.followups_due`，副「个岗位到跟进时间」，→`#module/jobs`；**通知待处理** = failed+unknown 条数，副「条投递状态待确认」，→`#module/notifications`。

### ⑤.1 数据契约（视觉值由视觉专家补，本表只定数据来源与缺失行为）

**行 A · 今日待办（3 格）**

| 格 | 唯一数据来源 | 取值 | 副文案 | 跳转 | 字段缺失时 |
|---|---|---|---|---|---|
| 到期复习 N 张 | `GET /api/notifications/daily-preview` → `counts.reviews` | `counts.reviews`（整数） | 「张卡片待巩固」 | `#module/learning` | 显示 **—**（em dash），**不显示 0** |
| 待跟进岗位 N 个 | `GET /api/notifications/daily-preview` → `counts.followups` | `counts.followups`（整数） | 「个岗位到跟进时间」 | `#module/jobs` | 显示 **—** |
| 通知待处理 N 条 | `GET /api/notifications` → `notifications[]` | `notifications.filter(n => ["failed","unknown"].includes(n.data.status)).length` | 「条投递状态待确认」 | 铃铛面板（就近，见 ①） | 显示 **—** |

> **`limit=100` 的截断坑（前端必须处理，不必动后端）**：`platform/notifications.py:129` 的 `listing()` 是 `store.list("notification_outbox", limit=100)`，而 `record_store.py:223` 是 `ORDER BY updated_at DESC, id LIMIT 100` —— **只返回最近更新的 100 条**。outbox 超过 100 条时，更早的 `failed`/`unknown` 会被**漏算**，第三格数字会偏小。
> 处置：**队列长度达到 100（命中上限）时，第三格显示「100+」而不是「100」**，并在铃铛面板「待处理队列」区注明「只统计最近 100 条队列记录」。纯前端的诚实做法，不必新增后端端点。
> 状态取值域是 `pending / sending / sent / failed / unknown / cancelled`。**只数 `failed` 与 `unknown`**——`pending`/`sending` 是「在途」，`sent`/`cancelled` 是「已了结」，都不是需要用户决策的未解决项。

**唯一来源裁决（避免首页出现两个不一致的数字）**
- **到期复习 / 待跟进岗位 统一用 `daily-preview.counts`**。`daily-preview.counts.reviews` 与 `learning/cards.due_ids.length` 口径一致（`not paused and due_at <= now`，已逐行核对 `platform/learning.py` 与 `platform/weekly_report.py`）；`counts.followups` 与 `jobs/report/weekly` 的 `metrics.followups_due` 口径一致（`status ∉ {offered,rejected}` 且 `follow_up_at <= now`）。**但首页只认 `daily-preview` 一个来源**——它是 boot 期就位、且铃铛徽标与行 A 共用同一份快照的两个计数，不会出现「角标说 3、页面说 2」。
- **不引入 `jobs/report/weekly` 作为行 A 来源**：它要扫 7 类记录 + 版本表，是三个端点里最重的，且按 ④ 延后到 idle；等它到位再渲染行 A 会造成首屏数字闪烁。
- **通知待处理必须另拉 `GET /api/notifications`**：`daily-preview` 只读 `learning_card` 与 `application` 两类记录，**拿不到外发队列状态**。该请求**不在 boot 发起**，而是首页渲染后异步补齐（见下）。

**行 B · 本周与存量（4 格）**

| 格 | 唯一数据来源 | 取值 | 字段缺失时 |
|---|---|---|---|
| 知识条目 | `state.knowledge.length` | 已随 boot 加载 | 显示 **—** |
| 规划完成 | `GET /api/status` → `done_count` / `node_count` | `done_count`/`node_count`，`node_count=0` 时显示「0 / 0」 | 显示 **—** |
| 本周投递 | `GET /api/jobs/report/weekly` → `current.metrics.applications_submitted` | 整数 | 显示 **—**（idle 补齐前） |
| 本周复习 | `GET /api/jobs/report/weekly` → `current.metrics.reviews_recorded` | 整数 | 显示 **—**（idle 补齐前） |

**行 C · 细字链接行（不是统计块）**：`谨记名单` = `state.status.lessons_count`；`阶段记录` = `state.status.stages_count`。两者都来自 boot 已有的 `/api/status`，零新增请求。（原计划的「复习卡 N」项**取消**——卡片总数只在 `learning/cards` 里，而首页不拉该端点；用 `daily-preview` 也取不到总数。与其显示一个必须额外请求的数字，不如不显示。）

**加载时机与批次（修正后）**

| 端点 | 何时 | 用途 | 失败时 |
|---|---|---|---|
| `GET /api/notifications/daily-preview` | **boot 首批**（唯一必须 boot 拉的） | 行 A 前两格 + 铃铛徽标 + 铃铛面板摘要 | 行 A 前两格显示 **—**；徽标不显示数字；面板显示「暂时读不到今日摘要」+ 重试按钮 |
| `GET /api/notifications` | 首页首屏渲染后**异步补齐** | 行 A 第三格 + 铃铛面板「待处理队列」区 | 第三格显示 **—**；面板该区显示「暂时读不到队列状态」+ 重试 |
| `GET /api/jobs/report/weekly` | `requestIdleCallback` | 行 B 的「本周投递 / 本周复习」 | 两格显示 **—**，idle 补齐后替换 |
| `GET /api/status` | boot 首批（已在 `load()` 里） | 行 B 规划完成、细字行 | 显示 **—** |

> **「—」与「0」必须区分**：0 = 「确实没有」，— = 「还没读到」。把「还没读到」画成 0 会让用户误以为「没有失败项 / 没有到期项」，这是比缺数字更糟的错误。徽标同理：计数未知时**不显示数字**（不是显示 0）。

**该删 / 该改 / 该保留**：
- **删「谨记名单」**——它和 `lessons` 模块是同一个数字，一个在首页一个在侧栏 = 同一事实两处维护。
- **删「阶段记录」**——日志类计数，无行动信号；且 `stages` 已从环轨退到分组页，首页再挂计数是双重降权。**注意这是「内环 6 位」的连带代价**：阶段记录从环轨退到分组页后，首页也同时不再显示其计数，两处一致，不会显得被边缘化。
- **改「任务完成」→「规划完成」**——它数的是 plan 的 node 不是通用任务；且**直接用 `/api/status` 的 `done_count`/`node_count`**，不再前端遍历 `state.plans` 复算：现有 `homeStats()` 里那段 `try/catch` 在 `plan.data.acts` 结构异常时会**静默变成 0**。
- **降级为细字行**（不是统计块）：`谨记名单 12 · 阶段记录 8`，各带链接——数字仍可见，但不与模块争视觉权重，也不制造「零」的心理暗示。
- **行 A 空态**：三格**全为 0**（不是缺失）时，收敛为一行「今天没有到期的事」+ 一个次要链接「去复习 →」。**保留这一行、不隐藏整行**——用户来首页就是为了确认「今天没事」，整行消失会造成布局跳动（进入时 3 格、消失时 0 格）。三格是 **—**（未读到）时**不折叠**，保持 3 格占位，避免把「没读到」渲染成「没事了」。

**数据来源**：`GET /api/notifications/daily-preview`、`GET /api/notifications`、`GET /api/jobs/report/weekly`、`GET /api/status`、`state.knowledge` —— **全部已存在，无新增端点**。
**改动文件**：`views.js`（`homeStats()` 重写、`home()` 新结构）、`data.js`（`load()` 加 `daily-preview`、`state.digest`/`state.queue`/`state.weekly`）、`app.css`（行标题/行栅格/强调色/空态）。

---

## ⑥ 首页该有多「满」

**结论**：`.home-main` 分 **6 段**，顺序是「**氛围 → 该做的 → 我有什么 → 产出了什么 → 明细 → 最近**」。

| # | 段 | 内容 | 视觉权重 |
|---|---|---|---|
| 0 | hero | 插画 +「时列」+ 问候日期 | 氛围，最弱 |
| 1 | 今日待办 | ⑤ 的行 A（3 格） | **最强** |
| 2 | 本周与存量 | ⑤ 的行 B（4 格）+ 细字行 | 中 |
| 3 | 求职周报摘要 | 一行 4 个数字 +「查看本周周报 →」 | 中 |
| 4 | 今日到期 | 保留现有 `.due-panel`，≤5 条 +「共 N 项」 | 弱（明细） |
| 5 | 最近 | 双栏：最近笔记 ǀ 继续上次工作 | 弱 |

**hero 两个改动**：① **删掉 hero 里的「快速打开搜索 Ctrl K」按钮**（顶栏已有同一个，重复入口），改为 hero 右下角一行**状态摘要**「3 项待办 · 本周投递 2」；② hero 高度上限：桌面 **320px** / 移动 **180px**，`object-fit:cover` + 压暗遮罩。

**`.home-main` 的 DOM 顺序（给前端排首屏用）**——`home()` 渲染出的结构必须是这个顺序，**「今日待办」紧跟在 hero 之后、在任何其它分区之前**：
```
section.home-main
├─ section.home-hero            插画 + 品牌 + 问候 + 状态摘要行   ≤320px
├─ section.today-overview
│  ├─ h2「今日待办」                                  ← 分区标题
│  ├─ nav.stat-grid.stat-grid--todo     ← 行 A：3 格（待办）
│  ├─ h2「本周与存量」
│  ├─ nav.stat-grid.stat-grid--state    ← 行 B：4 格（存量/周度）
│  └─ nav.stat-meta-line               ← 行 C：细字链接行
├─ section.weekly-strip              求职周报摘要（4 数字 + 链接）
├─ section.due-panel                 今日到期（≤5 条 + 共 N 项）
└─ section.recent-split              最近（双栏：最近笔记 ǀ 继续上次工作）
```
**「今日待办」行的锚点类名 = `.stat-grid--todo`**，行 B = `.stat-grid--state`。首屏硬指标靠这个顺序 + hero ≤320px 达成：**76 顶栏 + 320 hero + 分区标题 + 行 A ≈ 560px**，1440×900 下有 340px 余量（导航条 `navigation-strip` 只在非首页显示，首页不占位）。

**插画与统计的分工（明确回答）**：**插画是氛围与定位，不承载任何数字；统计是数据，不放进插画里**。当前「插画 + 统计块各自独立」是对的，问题只在 hero 面积过大、把数据推到折叠线以下。**硬指标**：**1440×900 视口下，hero + 行 A 待办必须完整落在首屏**（76 顶栏 + 320 hero + 分区标题 + 待办行 ≈ 560px，留足余量）。**「满」的尺度**：首屏填充率目标 55–65%（内容区高度），滚一屏能看到行 B + 周报摘要，「最近」允许延后——**数据区留白要比插画区少，但不满到 100%，满了就没有层级了**。

**数据来源**：同 ⑤。**改动文件**：`views.js`（`home()` 重写、hero 结构）、`app.css`（hero 高度/摘要行/新分区栅格）。

---

## 响应式策略

**总原则：一律用 `@container`，不用 `@media`**——portal 与 sidebar 两套布局内容区差约 260px，视口断点会在同一视口下给出两套布局。现有环轨已是 `@container(min-width:610px)`，新代码沿用同一基准。**容器基准是 `.home-orbit-wrap`（`container-type: inline-size`），不要加到 `#content` 或更上层**——会波及 toast / cursor-glow / petal / fireflies 等 fixed 定位元素。

| 内容区宽度 | 今日待办 | 本周与存量 | 最近 | 铃铛面板 |
|---|---|---|---|---|
| ≥760px | 3 列 | 4 列 | 双栏 | 360px 下拉 |
| 560–759px | 3 列紧凑 | 2×2 | 单栏 | 360px 下拉 |
| <560px | 纵向堆叠（每项 44px 高，图标左、数字右） | 2×2 | 单栏 | 底部抽屉 100%/70vh |

- **环轨降级口径（已拍板）**：**保留 610px 容器口径**。
  > **为什么是 610 而不是 960 —— 请把这段写进代码注释，否则下一个人会改回去**：
  > ① portal 与 sidebar 两套布局的**内容区宽度差约 260px**，只有容器口径能分别判断；视口断点会在同一视口下给出两套布局。
  > ② 环轨真实最小宽度 = `2×250（外环直径）+ 64（外环节点直径）` = **564px**，610px 已覆盖并留 46px 余量。
  > ③ 960px 视口规则在 **portal 模式**下（内容区 = 视口宽）会让 700–959px 宽的窗口无谓地退化成两列列表——那段时间里环轨完全放得下。
  > ④ 反向也不对：若阈值低于 564px，环轨会出现横向溢出或节点被裁切。
  >
  > 实现口径：`.sl-orbit { display:none }` + `@container (min-width: 610px)` 切回环轨；窄屏列表 `.sl-orbit-list` 两列、条目 44px 高、图标 + 文字。
  > **容器基准是 `.home-orbit-wrap { container-type: inline-size }`（app.css:6136），绝不能加到 `#content` 或更上层**——那会创建包含块，波及 toast / cursor-glow / petal / fireflies 这些 fixed 定位元素。

  > ⚠️ **动手前必读：现在 `app.css:6959` 还有一条活的 `@media (max-width: 959px)` 兜底规则，它会覆盖容器查询。**
  > 我用真实 Chromium 实测过级联（同样的规则组合，`container-type: inline-size` 的 wrapper）：
  > ```
  > 视口1440 / 容器1200  → 环轨:block  列表:none
  > 视口1000 / 容器1200  → 环轨:block  列表:none
  > 视口 959 / 容器1200  → 环轨:none   列表:grid   ← 媒体查询在这里翻盘
  > 视口 900 / 容器1200  → 环轨:none   列表:grid
  > ```
  > 两条规则**选择器相同、源序在后**，所以媒体查询胜出。**当前真实生效的规则是「视口 ≥960px AND 内容区 ≥610px」**，不是纯容器口径。
  > **要落到 610px 容器口径，必须删掉或前移那个 `@media (max-width: 959px)` 块**——只「不新增」它是不够的。
  > 顺带：`app.css:6955` 的注释（「960 视口是分界：portal 模式可用 880px、sidebar 模式 960−224−80=656px」）与容器口径的结论矛盾，一并改掉。
  > （`app.css:6883` 那处 960px 确实只是注释，可以不管。）
- **触控**：新增交互元素命中区 ≥44×44；hover 样式包在 `@media (hover:hover)` 内（避免移动端粘滞 hover）；`prefers-reduced-motion` 下徽标数字变化不动画（仓库已有 4 处该断点，沿用）。

## 无障碍清单

1. **铃铛**：`aria-expanded`/`aria-controls="notify-panel"`；数字徽标 `aria-hidden="true"`，另置 sr-only 文本「3 项待处理」——**徽标数字本身是文本，颜色只是冗余信号**。
2. **计数播报**：独立 `aria-live="polite"` 元素。**首屏加载不播报**（避免每次开页都吵），仅用户手动刷新后播报差异（「待办 3 → 2」）。
3. **面板**：非模态 popover（非 `dialog.showModal`，无背景遮罩）；Esc 关闭；关闭后焦点归还铃铛；Tab 自然流出，不做焦点陷阱。
4. **环轨节点**：`learning` 节点 `aria-label` 改为「**到期复习，3 张卡片待巩固**」（数量进无障碍名，不进视觉）；中心胶囊 `aria-label`「进入工作区，今日 3 项待办」。
5. **数字不靠颜色**：行 A `value>0` 同时给出文字（「3 项待处理」），颜色仅强化；徽标同理。
6. **对比度**：徽标底/数字 ≥4.5:1；强调色与纸底 ≥3:1；`app.css` 有独立黑化版本，**深色轮次需单独验算这 3 处**（铃铛徽标、行 A 强调色、hub 胶囊）。
7. **焦点可见**：新增卡片/徽标**不得移除** `:focus-visible` 轮廓；行 A/B 每格是 `<a>`，保持可聚焦。
8. **语义**：行 A/B 用 `<nav>` + `<a>`（可直接跳转），禁止 `div + onclick`。
9. **字号下限**：沿用仓库既有约定——**正文与环轨标签均不低于 11px**；窄屏列表项 44px 高、图标 `aria-hidden`。
10. **焦点顺序**：顶栏 铃铛 → 齿轮 → 快速打开；首页 hero → 待办 → 状态 → 周报 → 到期 → 最近，与视觉顺序一致；`prefers-reduced-motion` 下环轨静止，键盘用户不被旋转动画打断。

---

## 改动顺序建议

**批次 1（必须原子发布，否则报错）**——`data.js` 的 `groups`/`modules` + `views.js` 的 `ORBIT_INNER`/`ORBIT_OUTER`/`category()`/`sidebar()` + `app.js` 的 `updatePosition()`。
> 原因：`updatePosition()` 里 `groups.find(g=>g.id===module.group)` 找不到就取 `group.title` → TypeError。只改 `modules[].group` 而不同步加 `groups` 条目，**除首页外每一页都崩**。本批同时交付：jobline 分组、learning 进内环、stages 退到分组页、settings 移出外环（否则 `settings` 在环轨外失去一级入口）。

**批次 2（必须原子发布）**——`data.js` 的 `load()`（**boot 只加 `notifications/daily-preview` 一个端点**；`notifications` 列表首屏后异步补齐；`weekly` 延后 idle）+ `views.js` 的 `homeStats()`/`home()`。
> 原因：徽标、行 A 前两格、中心胶囊三处读 `daily-preview` 的**同一份快照**；分两批会出现「角标说 3、页面说 2」的不一致。含 ⑤ 全部改动（含 ⑤.1 数据契约）与 ⑥ 的 6 段结构。
> **boot 不必拉 `learning/cards`**：徽标与到期复习数都用 `daily-preview.counts.reviews`，口径与 `due_ids.length` 相同（已核对），少一个请求。

**批次 3（可独立上线）**——铃铛+面板：`index.html`+`app.js`+`app.css`+`icons.js`+`learning.js`（模块改名「通知与外发」）。依赖批次 2 的 `daily-preview` 缓存，但可用空态独立上线（徽标不显示）。
**批次 4（可独立上线）**——Ctrl+K 升级为命令面板：`app.js`+`index.html`+`app.css`。与前三批无耦合。
**批次 5（可独立上线）**——求职周报摘要条：依赖批次 2 已加载 weekly 数据。
**批次 6（可独立上线，排最后）**——范围提示文案统一：`views.js` 抽出 `MODULE_META` 表，`category()` 与模块页副标共用。

**明确不做（本轮）**：预取 `/api/jobs`、`/api/lessons` 让 Ctrl+K 覆盖岗位与卡片（首屏 +3 请求，收益不足）；「已读」语义与 `read_at` 字段（与「状态即真相」哲学冲突）；内环扩到 7 位（已拍板 6 位，`stages` 退分组页且首页同步删其计数格）；**接 `POST /api/chat` 对话检索**（见 ④）；**接 Skill 市场 / MCP 服务器管理 9 个孤儿端点**（后端已就绪但需独立信息架构，单独立项；本轮**只在「自动化中心」分组描述加一行中性说明**，不写「界面尚未开放」这类给开发看的话）。

**跨批次的两个共享改造（建议在批次 2 一次做完）**：① `jobs/report/weekly` 的缓存从 `job-insights.js` **上提到 `data.js`**，由首页与周报页共用（避免首页周报摘要与周报页数字取自两个时间点）；② `views.js` 的 `category()` 描述三元表达式 → `MODULE_META` 数据表。
> **`learning/cards` 不需要上提**：首页的到期复习数走 `daily-preview.counts.reviews`，与 `due_ids.length` 口径相同（已核对），两者恒等；`learning.js` 继续自持缓存即可，**少一个请求**。
