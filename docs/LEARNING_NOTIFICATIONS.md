# 到期复习、确认建卡与通知 outbox

## 真实使用闭环

1. 求职记录 → 面试复盘 → “选点创建复习卡”。勾选需要复习的薄弱点，点击确认。未勾选/取消不会写入；重复确认复用原卡。源复盘版本改变时先重新读取，不静默接受旧建议。
2. 到期复习页先回忆，再显示答案或资料引用，按忘了/困难/记得/熟练自评。服务端原子更新间隔并记一条不可变复习证据；重试使用同一请求标识，不重复推进。未到期或暂停卡片不能重复打分。
3. 可添加手工卡，编辑正文/答案/暂停/目标时间；普通编辑不能伪造来源、难度和次数。回收站及显式历史恢复保留版本，复习证据不允许通用删除/恢复重放。
4. 通知中心先预览摘要，再确认入队。内容只含跟进岗位和到期问题标题，不含答案或私密日记。今日重复入队复用相同 operation_id，消息正文冻结；每日最多一份摘要，其中最多一条规则排序建议，不冒充 AI 个性化判断。

四档间隔为配置化启发式，不是经过本项目试验证明的记忆提升算法。错过复习日不清零；新间隔从实际复习时间起算。参数见 `config/learning.yaml`。通知日界线为 `config/notifications.yaml` 的固定时区偏移分钟，默认 UTC+08:00；不声称支持夏令时。浏览器日期显示为本地时区，持久化 UTC。

## SMTP 单通道，默认禁用

运行进程需要受保护环境变量（不要把密码写进聊天、代码、YAML 或发布包）：

```text
NOTIFY_ENABLED=true
SMTP_HOST=HOST
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_FROM=ADDRESS
SMTP_TO=ADDRESS
SMTP_USER=ACCOUNT
SMTP_PASSWORD=TOKEN
```

支持 `starttls`（默认）或 `tls`（通常端口465），均使用默认 CA 验证，不关闭证书校验。无鉴权服务器可同时省略账号密码，不能只配一项。`local-test` 明文模式只允许显式的 127.0.0.1，是隔离 SMTP 故障测试用的，不允许外网地址。

页面不收集 SMTP 密码；只显示启用/配置是否齐备，字段齐备不证明连接可用。仅在显式确认发送后才领取消息。生产通知账号/收件箱/环境注入和 cron 安装尚需部署授权，本轮不会擅自启用真实外发。

## 状态语义与异常

- `pending` 等待；`sending` 已领取并落库后执行外发；`sent` 表示 SMTP 已接受，**不证明收件箱/手机送达**。人工核对已收到会单独标注来源，不能冒充 SMTP 回执。
- 明确的连接/握手失败在 DATA 前发生，记 `failed`；安全可重试的失败按配置退避、有次数上限。账号/地址拒绝不自动重试，修改配置后需人工确认。
- DATA 阶段连接中断、发送后记账前崩溃等窗口，记/恢复为 `unknown`；**不自动重试**。只有核对实际收件结果并输入“已核对通知结果”后，才可标记收到或显式重试。未知状态重试仍有重复风险，页面明确告知。
- 同一通知 operation_id 不含 attempt；Message-ID 稳定用于查证，不保证收件服务器去重。并发 worker 使用行锁与 SKIP LOCKED，只领取一次；卡住的 sending 超过保守阈值才转 unknown。
- outbox 是当前版本表中的独立逻辑 kind，沿用同一事务/审计设施，不引入 Redis/MQ 或第二套表迁移。它被排除在公共导出/恢复之外，避免恢复旧备份重发通知；通用删除/历史恢复也会拒绝。后续若吞吐有真实需要，再独立评估专表。

## 有界 CLI 和调度

```sh
python scripts/daily_briefing.py                  # 只读预览
python scripts/daily_briefing.py --enqueue        # 明确入队，不自动发送
python scripts/notification_worker.py            # 只打印脱敏配置状态，无数据库写入
python scripts/notification_worker.py --confirm-send --limit 5
```

双脚本单次退出，没有进程内 scheduler 或无限循环。示例 crontab 在 `docs/cron/shilie-reminders.cron`，仅模板，未安装。**cron 不会自动继承 systemd 的 EnvironmentFile**；管理员必须先审查环境注入与文件权限，以受限服务账号运行，不能让 Agent 读取 root 专用环境文件或获得常驻管理员权限。先验证只读预览、备份与受限账号权限，再授权登记条目。未完成配置时不要启用模板。

## 验证范围

`release_gate.py --checks full` 在拥有随机身份的新建 PostgreSQL 上跑确认/拒绝/重复确认、并发重复评分、时间/权限/快照反例，以及本机真实 SMTP fixture 的接受、明确拒绝、丢回执、并发 worker 和 stale claim。所有 SMTP fixture 仅绑定 127.0.0.1，不发外网邮件。

真实浏览器 `verify-learning.mjs` 不用路由 mock；检查勾选确认、复习持久化、409 输入保留、暂停/回收站、通知默认关闭、重复入队及失败可见、390px。测试专用 SMTP 故障入口只由 `ci_verify.py --serve` 在核对随机 QA 身份后提供，不在产品 main.py 路由中。

未完成：真实私人收件箱端到端送达、生产定时器安装、七天真实学习记录、费曼追问与真实模型质量。当前证据不能替代这些验收；相关后续工作仍保留在总目标中。
