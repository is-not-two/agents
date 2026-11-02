# 时列工作台 · 端点可达性与模块覆盖审计

> 任务：任务二（核查孤儿端点与前端不可达功能）　｜　版本：v2（2026-11 修正）
> **v2 更正**：v1 报的「`server-status.js` 路径打错」是**误报**——`APIRouter(prefix="/api/admin")` + `@router.get("/stats")` 在运行时才拼成 `/api/admin/stats`，字面量 grep 找不到。v1 用「逐文件数装饰器」得出 110 端点，也是错的。**v2 全部改用 `app.openapi()["paths"]` 实测。**

## 0. 总账（唯一口径：`app.openapi()["paths"]`）

| 指标 | 数值 | 说明 |
|---|---|---|
| **path 总数** | **102** | `app.openapi()["paths"]` 的键数 |
| ├ `/api` 前缀 path | **97** | 业务端点 |
| └ 非 `/api` path | **5** | `/`、`/health`、`/health/live`、`/health/ready`、`/legacy` |
| **operation 总数** | **133** | 同一 path 上的 GET/POST/PUT/PATCH/DELETE 分别计数 |
| 前端 `api()` 调用点 | 101 处 | 解析第一个实参（字面量/模板/三元都展开） |
| 前端实际请求的唯一路径模式 | 66 条 | 剥离查询串、`${}`→`*` 后 |
| **孤儿端点（前端无任何入口）** | **11 path / 13 operation** | |
| ├ A. API-only（有 Python 测试覆盖） | **7 path / 7 operation** | 对外能力，故意不做界面 |
| └ B. 真死端点（既无前端也无测试） | **4 path / 6 operation** | |

> **写进 `AGENTS.md` 的唯一数字**：`102 条 path / 133 个 operation（其中 /api 前缀 97 path）`。
> 「110」是逐文件数装饰器的旧错值，「133」是 operation 数——**两者量的不是同一个东西**，必须写明口径。

### 与工程「24 个孤儿（18 API-only + 6 真死）」的对账

- **B 类完全一致**：工程 6 个真死 = 我 6 个 operation（4 个 path）。
- **差在 A 类**：工程 18 vs 我 7，差 **11**。
- 差的来源只有一个：**前端调用路径由变量/拼接/三元构造**时，朴素的字符串差集抓不到。下表 20 条是「脚本会误判为孤儿、但前端确实在用」的完整清单，逐条附证据——工程若要收敛，把这 20 条与其 24 条一减即可闭环。

| path | 前端调用形态 | 证据 |
|---|---|---|
| `/api/admin/stats` | 数组变量 → `api(path)` | `server-status.js:11` |
| `/api/mcp/status` | 同上 | `server-status.js:11` |
| `/api/admin/diagnostics` | 同上 | `server-status.js:11` |
| `/api/export` | **href 链接**（不走 `api()`） | `backup.js:33` |
| `/api/stages/{stage_id}/diff` | **href 链接**（含 `${}`） | `views.js:283` |
| `/api/collaborations/{run_id}/confirm` | `route(id) + "/confirm"` | `collaboration.js:112` |
| `/api/collaborations/{run_id}/execute` | `route(id) + "/execute"` | `collaboration.js:116` |
| `/api/collaborations/{run_id}/child-confirm` | `route(id) + "/child-confirm"` | `collaboration.js:121` |
| `/api/collaborations/{run_id}/abort` | `route(id) + "/abort"` | `collaboration.js:125` |
| `/api/jobs/applications` | `jobs/${paths[kind]}`，`paths.application="applications"` | `jobs.js:5,143` |
| `/api/jobs/applications/{record_id}` | 同上 | `jobs.js:5,143` |
| `/api/jobs/resumes` | `paths.resume_version="resumes"` | `jobs.js:5,143` |
| `/api/jobs/resumes/{record_id}` | 同上 | `jobs.js:5,143` |
| `/api/jobs/leads/{record_id}` | `paths.job_lead="leads"` | `jobs.js:5,143` |
| `/api/jobs/reports` | `paths.interview_report="reports"` | `jobs.js:5,143` |
| `/api/jobs/report/weekly/notify` | `"jobs/report/weekly" + (cond ? "/notify" : "")` | `job-insights.js:114` |
| `/api/learning/cards/{card_id}` | `learning/cards${id ? "/"+id : ""}` | `learning.js:136` |
| `/api/workflows/{record_id}` | `path + (id ? "/"+id : "")`，`path="workflows"` | `automation-actions.js:161` |
| `/api/workflow-runs/{record_id}` | `"workflow-runs/" + id` | `automation-actions.js:222` |
| `/api/private/{kind}`、`/api/private/{kind}/{record_id}` | `"private/wish/" + id` | `private-view.js:91,142,166` |

---

## 1. 13 个真孤儿 operation（前端无任何入口）

### A. API-only（7 op）——后端有意提供的对外能力，没有界面是**设计选择**，不是遗漏

| 端点 | 语义 | 测试覆盖 |
|---|---|---|
| `GET /api/capabilities` | 运行时能力清单 | `test_agent_capabilities.py` |
| `GET /api/skills` | Skill 列表 | `test_agent_capabilities.py` |
| `GET /api/skills/{name}` | 单个 Skill 详情 | — |
| `PUT /api/skills/{name}` | 更新 Skill | — |
| `POST /api/skills/github/preview` | 从 GitHub 预览可导入 Skill | `test_agent_capabilities.py` |
| `POST /api/skills/github/import` | 从 GitHub 导入 Skill | `test_knowledge_skill_import.py` |
| `GET /api/mcp/servers` | MCP 服务器列表 | `test_agent_capabilities.py` |
| `POST /api/chat` | 多轮消息 → 规则分流 + 检索引用 + 可选生成 | `test_admin_chat.py` |
| `POST /api/knowledge/import/markdown` | Markdown 批量导入知识 | `test_knowledge_skill_import.py` |

> 这 9 个 path（10 个 operation，含 `PUT /api/skills/{name}`）构成「**Skill 市场 + MCP 服务器管理 + Agent 工具清单**」产品面，落在 `automation 自动化中心` 的语义范围内。
> **裁决**：单独立项，本轮**不接**。本轮只在「自动化中心」分组描述加一行**中性**说明（不写"界面尚未开放"——那是给开发看的）：
> > 范围：工作流配置、Agent 与协作运行记录
>
> `POST /api/chat` 是**第四条真检索**（多轮对话 → 检索引用），**本轮不接**：④ 的目标是让用户知道该用哪个检索，范围标注体系没落地前再加一条入口会放大原问题。日后接入应挂成独立「对话」模块，Ctrl+K 的「全文」段仍走 `POST /api/query`（带引用）。
> `POST /api/knowledge/import/markdown` → 挂到「个人知识库」工具栏「新建笔记」旁作次级操作，不单独建模块。

### B. 真死端点（6 op）——既无前端也无测试

| 端点 | 语义 | 处置 |
|---|---|---|
| `GET /api/agents/{record_id}/tools` | Agent 可用工具清单 | 与 capabilities 一组，单独立项 |
| `GET /api/skills/{name}` | 单个 Skill 详情 | 同上 |
| `PUT /api/skills/{name}` | 更新 Skill | 同上 |
| `POST /api/mcp/servers/{server_id}/test` | 测试 MCP 服务器连通 | 同上 |
| `GET /api/jobs/applications/{application_id}/reports` | 某条投递下的面试复盘 | **本轮接入**（见下） |
| `POST /api/jobs/applications/{application_id}/reports` | 给某条投递追加复盘 | **本轮接入**（见下） |

**唯一建议本轮接入的孤儿**：`jobs/applications/{application_id}/reports`。前端现在只有 `GET /api/jobs`（一次全量）、`GET /api/jobs/reports`（全部复盘平铺）、`POST /api/jobs/reports`（新建复盘）。**「按投递聚合复盘」后端已支持、前端没接**——而它恰好是求职主线「投→记」那一步最自然的交互（在投递详情里直接写复盘）。接上后求职主线第 1 步才闭环。

---

## 2. v1 误报更正（重要）

### 2.1 「`server-status.js` 路径打错」——**不成立，不要修**

`server-status.js:11` 的 `paths = ["admin/stats", "mcp/status", "admin/diagnostics"]` → 拼上 `/api/` 前缀后为 `/api/admin/stats`、`/api/mcp/status`、`/api/admin/diagnostics`。
实测 `app.openapi()["paths"]`：**三个端点全部存在**。原因：`api/routes/admin.py:14` 是 `APIRouter(prefix="/api/admin")` + `:43` 的 `@router.get("/stats")`；`api/routes/mcp.py:212` 是 `APIRouter(prefix="/api/mcp")` + `:215` 的 `@router.get("/status")`——**路径在运行时由 prefix + 路由拼接而成，源码里搜不到字面量 `"admin/stats"`**。
**v1 用字面量 grep 判断路径存在性，这是方法错误。若按 v1 建议去掉 `admin/`、`mcp/` 前缀，反而会打坏本来正常的代码。**

### 2.2 CSS「死文件」判断更正

`scripts/merge_css.py` 的 `FILES = ['base.css','demo.css','tree.css','automation.css']` → 机械拼接成 `app.css`（文档明确说明**故意不去重**，以保层叠顺序）。
实测「规则原样出现在 app.css」的比例：

| 文件 | 当前目录版 | `_archived/` 版 |
|---|---|---|
| `tree.css` | 79/139（56%） | 0/240（0%） |
| `demo.css` | 135/194（69%） | 0/235（0%） |
| `automation.css` | 64/77（83%） | 0/79（0%） |
| `chapters.css` | **1/53（1%）** | 0/53（0%） |

**结论更正**：
- `tree.css` / `demo.css` / `automation.css`：**不是死文件，是 app.css 的 merge 输入源**；`_archived/` 里是更早的旧版本（旧的青绿主题），不是 app.css 的原件。**不要删**——删了会让下一次 merge 丢内容。
- `chapters.css`：**真孤儿**（53 条规则只有 1 条进了 app.css），且配套的 `planning.js` 无人 import、且 import 已失效 → 这一对该处理。
- `app.css.bak-before-blackhole`（134 KB）是 app.css 的备份副本，不该进版本库。

### 2.3 `planning.js` + `chapters.css` —— 成立，清理批次处理

- `planning.js` 被**无人 import**（全仓唯一未 import 的非入口模块；`app.js` 是 `index.html` 的入口脚本，不算孤儿）；
- 其 import **已失效**：`import { state, priorities, priorityNames } from "./data.js"`，而 `data.js` 只导出 `api / read / write / escapeHtml / groups / modules / state / plan / currentNote / load`——**没有 `priorities` 和 `priorityNames`**，一旦被引入即抛 SyntaxError；
- `chapters.css` 未被 `index.html` 链接，`app.css` 也无 `@import`，且几乎未并入 app.css；
- 二者配套：`chapters.css` 的 8 个类名（`story-chapter / chapter-index / chapter-body / story-board / fold-chevron / story-group / prerequisite-list / chapter-timeline`）**只被 `planning.js` 使用**。
- 现存规划视图是 `tree.js` + `tree-actions.js`（样式已进 app.css）。这是「剧情层级视图」整块功能的遗留物。

---

## 3. 复核方法（可重跑）

```bash
.venv/Scripts/python.exe <脚本>     # 必须用项目 venv，fastapi 装在这里
```

口径与三处关键处理（改脚本时不要丢）：
1. **端点表**：`from rag_tech_retriever.api.main import app` → `app.openapi()["paths"]`。**不要用逐文件数装饰器**（会漏掉运行时 prefix 拼接与动态注册）。
2. **前端调用**：解析 `api(` 后**跳过空白**取第一个实参；实参是三元/变量时**扫描整个 `api(...)` 调用内的所有字符串字面量**；匹配时**剥离查询串**并把 `${...}` / `{...}` 规范化成通配；**再补 `href="/api/..."` 形式**的链接。
3. **测试覆盖**：用**完整路径**匹配（参数段转 `[^/"]+`），不要按末段名匹配（会把 `skills/{name}` 误配到别的文件）。
