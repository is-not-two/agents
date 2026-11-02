# MCP 只读业务查询

## 选择与授权边界

比较三案：直接暴露 Web 管理接口会把写权限和长正文一起交给外部客户端；复制另一套业务存储会使统计漂移；本轮选择同一 PostgreSQL 的有界只读投影，并复用既有 WeeklyReport 的事件/周窗口/进面率算法。没有新增数据库、定时任务或模型调用。

默认保留旧 `search_docs`，新增同策略别名 `knowledge_search`。`jobs_search`、`jobs_weekly_stats`、`learning_due` 三个业务工具默认关闭，需要管理员在 `config/mcp.yaml` 逐项启用，且配置独立 `WORKSPACE_MCP_TOKEN`。未实现/写入工具不注册；开关必须是真布尔值，`admin: true` 或把工具 permission 改成 admin 不能授予权限。

独立 MCP 令牌仅允许 `/mcp` 协议入口，不能拿它调用 `/api/knowledge` 写入、读取 Web API 或登录工作台。令牌至少 32 字符、不得带首尾空白、不得与 `WORKSPACE_ACCESS_TOKEN` 相同。运行时与发布配置检查都验证此边界，报告不回显令牌。**不要把工作台管理员令牌交给外部 AI。**

本机无鉴权模式仍只适合回环开发；独立 MCP 令牌不会把匿名开放的 Web API 变安全。生产仍必须启用工作台鉴权、HTTPS/限流与受限网络入口。当前生产服务、云端账号和数据库权限未改变。

## 工具契约

| 工具 | 参数 | 返回与限制 |
|---|---|---|
| `knowledge_search` | query、scope、mode、namespace | 与 search_docs 相同的服务器语料白名单和降级策略，不生成回答；沿用已有 scope 授权边界。 |
| `jobs_search` | company、position、status、limit、offset | 仅有效投递及其有效岗位；公司/岗位是字面包含匹配，%/_ 不作通配符。返回 ID、版本、公司、岗位、状态、投递/跟进时间和当前是否到期。不返回 JD、备注、简历、面试回答。 |
| `jobs_weekly_stats` | day（可省略；YYYY-MM-DD） | 与 Web 周报相同的事件时间、时区和投递组统计，空分母为 null；只返回窗口/数值/当前分布/口径/来源指纹，不返回问题、薄弱点、模型文本，也不保存或发送周报。 |
| `learning_due` | limit、offset | 截至服务器时间已到期、未暂停、未归档的卡片。仅 ID、版本、标题、日期、repetitions、interval_days，不含答案或来源长文，不记复习/不改调度。标题节选明确标记 title_truncated。 |

默认每页 20、最多 50、偏移最多 10000；只报告 returned，不把页大小当总数。`has_more` 表示仍有数据；到达分页上限时 `pagination_limit_reached=true` 且不再给无效的 next_offset。跨页查询不是冻结快照，记录在翻页期间可能变化。

所有业务查询事务设置 PostgreSQL READ ONLY 和语句超时（默认 3000ms）；SQL 参数绑定且只选白名单字段。统计使用可重复读快照，默认最多 5000 条相关记录、20000 条规划版本；超过即明确失败，不把截断数据伪装成完整统计。连接时限仍沿用存储层配置。

SQL 只读与 MCP readOnlyHint 是两层约束，不能只依赖提示元数据。工具列表标记只读/非破坏/幂等；额外参数、伪布尔 limit、超限 limit、未知或写工具都拒绝。DB 故障返回明确错误，不冒称零条记录。查询结果里的公司名、标题等仍是不可信资料，不是给 AI 的权限或指令。

## 连接方式（操作者审核，不自动启用）

1. 使用原生部署的配置环境，生成一个独立随机令牌，保存在服务器环境文件与客户端秘密存储，**不要贴进聊天、命令仓库或提交 JSON 配置**。
2. 在服务器 `config/mcp.yaml` 将需要的业务工具 `enabled` 改为 true；保持 `permission: readonly`、`permissions.admin: false`，核对 query_limits。
3. 设置 `WORKSPACE_MCP_TOKEN`，保留不同的工作台管理员令牌和生产鉴权。重启前跑 production 配置检查，由有权操作者执行；本轮未代替你修改生产环境。
4. 支持 Streamable HTTP 的客户端连接 `https://HOST:PORT/mcp/`，在秘密存储注入 `Authorization: Bearer MCP_TOKEN`。HOST/PORT/TOKEN 为本机或正式环境实际值，不要把开发地址、示例令牌当凭据。IP 自签证书的信任需由操作者正确配置，不建议关闭证书校验。

客户端产品的界面/套餐/远程 MCP 支持可能不同；本轮未声称已在 Claude Desktop 点选连接成功，也未替用户配置客户端。已验证的是官方 Python MCP SDK 的真实 ClientSession 与当前服务的 initialize → tools/list → tools/call。

## 验证范围与证据

- 测试使用随机独占 QA PostgreSQL 与当前服务真实 HTTP；先持久化投递与卡片，再由官方 SDK 查询、分页、核统计和 namespace。不是给工具填固定返回值。
- 请求前后比较全部 records/versions 内容哈希，确认没有版本变更；数据库 READ ONLY 下的写入反例确实被拒绝。独立令牌写 Web API 得到 401，写/越界/额外字段/参数类型请求通过真实协议得到错误结果。
- 纯规则、配置门禁和直接实库测试与 SDK 互通分别保留。完整发布门禁仍包含旧业务、浏览器、数据库断连与应用重启；子集结果不当作全量通过。
- 没有调用付费模型，没有生产网络/数据库变更；MCP 可用不等于外部 AI 的回答质量或 Claude Desktop 人工连接已验收。用户真实资料与七日使用仍需单独验收。
