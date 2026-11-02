# 运维、发布门禁与 CI/CD

## 当前边界

仍是单用户工作台，不是多租户 SaaS。企业化先补可观察、可复验、可阻断的发布链，不新增 Redis、账号体系或构建工具。HTTP 的既有部署口径不改；鉴权令牌在 HTTP 信道上的风险没有因为 CI 而消失。

## 运行诊断

- `/health/live`：只判断进程可响应，不碰数据库。
- `/health/ready`：只读 SELECT 1，连接和语句超时从 `operations.readiness_timeout_seconds`（2–10 秒）读取；失败 503，不回传 DSN/底层错误。
- `/health` 保持旧契约兼容；Compose 的容器探针改用 `/health/ready`。
- 系统设置→界面偏好→服务状态与运行诊断：刷新、逐项结果、下载脱敏 JSON。接口 `/api/admin/diagnostics` 沿用全局令牌保护，不允许从网页启动发布或执行 shell。
- 所有 YAML 配置拒绝重复键，包括嵌套映射；限流键已去重。默认本机/Compose 对外端口统一 8770，容器内部仍为 8000，显式 WEB_PORT 不被覆盖。

## 发布门禁

```sh
python scripts/release_gate.py --checks config --report output/ci/config.json
python scripts/release_gate.py --checks quick --report output/ci/quick.json
python scripts/release_gate.py --checks full --backend native --native-session OPERATOR_SESSION_JSON --report output/ci/gate.json
python scripts/release_package.py --report output/ci/gate.json --output output/ci/release.zip
```

config 检查配置；quick 再检查依赖兼容、产品源码 Ruff、缓存版本、JS 语法与离线 Agent/协作契约；full 再跑独占 PostgreSQL 上的完整 pytest、全部业务浏览器场景、真实 MCP SDK、数据库/应用故障恢复五阶段及 live/ready 故障检查。生成证据目录下的测试夹具不属于产品 lint 范围。任何阶段失败都不能打包。

当前默认原生 full 后端需要管理员准备的隔离原生 QA 会话，以及桌面的 Chrome/Edge、Node/npm 和已缓存的 `@playwright/cli@0.1.22`；桌面只运行浏览器/SDK客户端，应用与数据库仍在服务器。`OPERATOR_SESSION_JSON` 是本轮私有 transport 配置的绝对路径，详见 `docs/NATIVE_RELEASE.md`。未提供会话就失败，不隐式回退 Docker。GitHub 托管 CI 可显式传 `--backend docker` 使用自有标签的临时容器；它不能指向用户库、启动本机引擎或接管生产服务。可设置 PLAYWRIGHT_MODULE 指向缓存工具自带的 playwright/index.mjs。本机首次缓存：

```sh
npx --registry=https://registry.npmjs.org --yes --package @playwright/cli@0.1.22 playwright-cli --help
```

测试向量只是语料 SQL 夹具的合成单位向量，不是语义检索质量验收。gate 非零即阻断后续打包；config/quick 报告、失败报告、源已变更的 full 报告均不能生成发布包。包只含允许的源目录和部署文件，不含 data、.env、用户导出、备份或运行日志。报告不是抗恶意仓库写权限攻击的签名凭证；CI 受保护的工作流才是执行信任边界。

生产环境预检显式使用 `--profile production`，运行服务时设置 `WORKSPACE_PROFILE=production`；必须 `WORKSPACE_REQUIRE_AUTH=true`、访问令牌至少 32 字符、数据库口令至少 16 字符且非示例值、启用限流。报告仅输出是否合格，禁止输出凭据值。本地模式允许无令牌但提示受控环境边界。

## 原生部署边界（2026-10-31）

服务器运行时与当前原生完整门禁均不要求 Docker。Docker 仅保留为显式选择的托管 CI/旧开发 QA 后端；QA 镜像固定为内容摘要，升级摘要必须重跑全门禁。`docs/NATIVE_SCHEMA.md` 区分生产只读结构核验与管理员显式迁移；`docs/NATIVE_BACKUP.md` 区分原生备份与独立空库恢复；`docs/NATIVE_RELEASE.md` 描述版本切换和失败恢复；`docs/DEPENDENCY_PROVENANCE.md` 说明离线溯源与尚未完成的 Linux 依赖锁验证。

代码升级不能隐式取得管理员数据库权限，也不能自动回滚数据库。新版本若要求不向后兼容的结构，必须先停在管理员审核步骤；不得用恢复旧代码掩盖数据不兼容。备份、源码包和运行环境是三个独立产物，源码包不是带依赖或带数据的服务器安装包。回退测试使用独占本地目录/进程/数据库，不代表生产 systemd 和真实服务器已验收。

## CI 与 CD 路线

`.github/workflows/ci.yml` 在 push main/master、PR 或手动触发时跑同一个 full 门禁。官方 Actions 固定到完整 SHA，contents:read，checkout 不持久化凭据；PR 不读取生产 Secrets，不用 pull_request_target 执行 PR 代码。

`.github/workflows/release.yml` 只允许手动触发，重新全量验证当前同一提交后才打包，并上传 ZIP/SHA-256。它没有 SSH、生产 Host 或自动部署步骤，不把“发布包就绪”冒称为“生产部署成功”。推送前这只是本地工作流定义，必须实际观察 GitHub 运行后才可声称云端 CI 通过。

后续真正 CD 需要制作人确认 HOST、部署目录、回滚版本保留策略和凭据来源；凭据只进入 GitHub Environment Secrets，不写仓库。仓库管理员应设置受保护分支 required status=CI/verify，并为 release environment 配置允许分支/审批（平台套餐支持范围以 GitHub 文档为准）。未来部署顺序：同提交已验证产物→校验 SHA→备份→发布→ready 验收→失败回滚；未确认这些信息前不接触真实服务器。

参考：
- [GitHub deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
- [Official checkout](https://github.com/actions/checkout)、[setup-python](https://github.com/actions/setup-python)、[setup-node](https://github.com/actions/setup-node)
- [Playwright CI](https://playwright.dev/docs/ci)
