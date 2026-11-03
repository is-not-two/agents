# 求职记录：岗位、投递、跟进与面试复盘

入口：工作区 → 个人工作台 → 求职记录，或 `/#module/jobs`。

本功能在源码与隔离环境交付；不代表生产服务器已经升级。服务器当前仍需单独授权发布与新增记录类型约束迁移，不重新安装 Docker，不由应用自行提权。

## 日常使用

1. 添加岗位：填写公司、岗位名称，可粘贴原 JD 和来源 URL。服务端不抓取来源网页。
2. 可先登记简历版本名称、SHA256 和真实亮点，再在投递时关联。仅保存元数据，不读取/搬运本机简历文件。
3. 在岗位详情添加投递：选择渠道和简历版本、设置下一次跟进时间。已收藏 → 已投递 → 跟进中/面试中 → offer/结束；跳转不合规会明确拒绝。首次进入已投递可自动记录投递时间。
4. 到面试阶段后记录实际问题、当时回答、自评、薄弱点和下一步行动。薄弱点显示为待确认复习候选；本批不会自动建卡、发通知或伪造 AI 结论。
5. 用“待跟进”筛选查看已到跟进时间的有效投递；日期输入按浏览器本地时区解释，服务端统一存 UTC。结束或 offer 的记录不再计入待跟进。

## 可靠性与恢复

- 内容以 PostgreSQL 为事实源；刷新页面可重新读取，业务内容不进入 localStorage。
- 更新必须携带当前 version；409 时弹窗不关闭、输入不丢失，提示先保留本次内容后重新读取，不能自动用新版本盲目覆盖。
- 同一岗位不重复创建有效投递；并发提交受求职业务事务锁保护。
- 存在关联投递时不能归档岗位/简历版本；存在复盘时不能归档投递。先归档子记录，再归档父记录。恢复按相反顺序进行，父项缺失或归档时拒绝恢复孤立子项。
- 历史恢复会产生新版本，保留原内容；“恢复此版本”是用户明确动作，不是普通状态跳转。
- 导出/导入包含求职记录；导入预览校验关联类型与缺失父项。JSON 保留结构，Markdown 同时输出字段正文，不只输出标题。

## 求职漏斗与目标公司能力

- 求职记录页顶部显示四阶段漏斗：收藏 → 投递 → 进面 → Offer。进面按已登记面试复盘计，Offer 按当前状态计，两者不保证严格嵌套，页面已注明口径。
- 空分母显示“暂不计算”，不伪装成 0%。本周投递目标来自 `config/jobs.yaml` 的 `jobs.funnel.weekly_application_target`，周窗口按 `notifications.yaml` 时区从周一起算。
- 目标公司能力是独立记录类型 `company_capability`：公司、岗位、来源、能力清单（名称 / 硬性要求或加分项 / 重要度 1–5 / 证据状态 / 证据说明）与备注。页面不自动判定“满足/不满足”，只呈现用户填写的事实。
- 入口：工作区 → 个人工作台 → 目标公司能力，或 `/#module/company-capabilities`。能力记录支持历史版本、回收站恢复与导出；同名能力重复会被拒绝。

## 简历上传与解析

- 求职记录页新增「上传简历」：支持 PDF / DOCX / TXT / Markdown，最大 10MB；上传即解析。
- 公开的 `resume_version` 只保存标题、文件名、SHA256、大小、解析状态等元数据；解析文本与结构化段落保存在服务器 `data/local/resumes` 私密目录，不进入公共备份。
- 详情可查看结构化段落、技能命中和版本差异；`POST /api/jobs/resumes/{id}/analyze` 把目标岗位 JD 与简历文本对照，只报告文本命中与缺口，不认定真实能力。
- PDF 仅支持文本版；扫描图片版暂不做 OCR。

## API

`GET /api/jobs?trash=false` 提供一致的业务列表、状态计数、到期投递 ID 与漏斗统计（`funnel`）；回收站模式下 `funnel` 为 null。

`/api/jobs/leads`、`/api/jobs/applications`、`/api/jobs/reports`、`/api/jobs/resumes`、`/api/jobs/capabilities` 各支持 GET 列表、POST 创建、GET 单条、PUT 全量更新、PATCH 合并更新。写请求为 `{data: {...}, version?: N}`，编辑必须提供 version。

`GET/POST /api/jobs/applications/{id}/reports` 可按所属投递读取/新增面试复盘；路径和正文所属投递不一致时拒绝。

简历：`POST /api/jobs/resumes/upload`（multipart，字段 `file`、`title`）、`GET /api/jobs/resumes/{id}/document`、`GET /api/jobs/resumes/{id}/diff?against=...`、`POST /api/jobs/resumes/{id}/analyze`（`{lead_id}`）。

软删除、历史和恢复复用 `/api/records/{id}`、`/{id}/history`、`/{id}/restore`，求职记录走关联保护服务。现有鉴权、同源检查、限流与错误脱敏保持适用，不增加外部写入权限。

## 验证

领域反例：`python -m pytest tests/test_jobs.py -q -k 'pure or bad or timezone'`。

数据库/浏览器必须通过 `python scripts/release_gate.py --checks full --report output/ci/gate.json` 运行，测试自行创建带所有权标签的隔离数据库，不能指向用户原库。浏览器脚本 `scripts/verify-jobs.mjs` 还会核验随机 QA 身份，拒绝生产地址或身份不符的服务；不用路由 mock 验证业务写入。

本批证据见 `output/product-20261028/r1/`。真实 JD 分析、自动通知、复习卡片闭环分别在 R3/R2 推进，未完成前不标成功。
