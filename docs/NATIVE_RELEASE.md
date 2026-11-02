# Native release：显式升级与失败恢复（RELEASE-B）

适用单用户 Ubuntu 原生 Python 部署；不依赖 Docker、systemd 或 root。控制器只操作管理员明确选择的专用安装目录，不接管既有未知进程，不安装依赖，不执行 SQL 迁移或数据库降级，不删除数据库/旧版本。所有 OS 使用同一种原子 JSON 版本指针；不依赖目录 symlink，不接管旧 symlink 安装。Windows 可用于跨平台测试，Linux 的真实进程退出验证需独立实测。

## 信任与前置条件

1. 管理员准备专用、本地、当前用户拥有且不可被组/其他用户写入的目录；不是项目 checkout，也不是共享/NFS/不可信上传目录。父路径不得有 symlink/junction。管理员和受管目录写入者属于信任边界；这是本地 SHA/完整 gate 校验，不是来源签名或恶意管理员隔离。
2. 管理员为版本准备独立 venv；Python/依赖已安装。升级期间绝不运行 pip、apt、迁移或任意 shell 命令。Linux venv 的 Python 可为管理员明确批准的系统解释器链接；解释器文件与 runner 都用 SHA 钉定。**Windows venv 的 `Scripts/python.exe` redirector 不受支持**：其 Popen PID 与实际 Python PID 可能不同，必须显式批准 base Python（例如 `sys._base_executable`），并以 `--site-packages VENV/Lib/site-packages` 批准依赖目录。runner 在 isolated 模式中只加入该目录与当前 staged `src`（Windows 另显式加入其固定 pywin32 子目录和 DLL 目录，以支持 MCP；不执行 `.pth`）；不执行 `.pth` 或激活脚本。依赖目录本身的可信性由管理员保证，controller 不声称为整个 venv 做供应链证明。
3. 以 RELEASE-A 管理员流程预先迁移数据库。运行账号必须通过 production `verify_schema(require_runtime_role=True)`：当前记录表需 SELECT/INSERT/UPDATE，历史表仅需 SELECT/INSERT，禁止历史表的表级或列级 UPDATE；新旧代码对同一当前数据库结构兼容。每次 activate 必须显式 `--schema-compatible`。代码回退不是数据库回滚；不兼容迁移需要独立维护窗口和人工恢复方案。
4. 生产鉴权、数据库口令、限流等以真实环境变量注入；不把凭据写进包或命令 argv。控制器不打印继承 env 或子进程 stdout/stderr；应用子进程输出默认丢弃，失败只报告固定脱敏类型；preflight stderr 仅将匹配白名单的 APPLICATION/DEPENDENCY/LIFESPAN/SERVE 固定错误码公开，任意其他内容均不回显。管理员排障应另行选择受控日志方案。
5. 当前版本必须由本控制器启动，`RUNNING.json` 与实际 loopback 身份一致。已有 systemd/手动进程不能只靠改版本指针冒充受管版本；管理员需先明确完成停机与首次 bootstrap。

## 目录与批准

```text
INSTALLATION/
  NATIVE-INSTALLATION.json       # 钉定绝对根路径
  inbox/                        # 管理员放入 ZIP、ZIP.sha256、完整 source gate JSON
  runtimes/RUNTIME/runner.py     # 管理员审核复制 scripts/native_app_runner.py
  runtimes/RUNTIME/APPROVED.json # Python路径及SHA、runner SHA；独占创建
  releases/RELEASE/              # 独占创建；已有/失败目录不复用，不覆盖
  shared/                       # 应用阶段日志/导出等可变数据根
    config/                     # 管理员显式准备的有效配置；不从版本自动覆盖
    data/                       # corpus、私密元数据、模型连接、skills等持久文件
    output/                     # 阶段日志等持久输出
  current.json                  # {schema:1,release_id:RELEASE}，原子替换
  previous.json                 # {schema:1,release_id:LAST_HEALTHY}
  RUNNING.json                  # release_id/source identity关联的PID、OS birth、随机nonce、port
  PENDING.json                  # 未完成事务恢复日志（存在即阻止普通activate）
  .native-release.lock          # O_EXCL独占锁；绝不自动清除疑似陈旧锁
```

以下 `ROOT`、`PYTHON`、`VERSION`、`RUNTIME`、`SHA` 是管理员替换的显式值。`--expected-project-root` 每次必须与安装 marker 的绝对根相等；不做自动寻找安装或当前版本。

```bash
python scripts/native_release.py init --project-root ROOT --expected-project-root ROOT
# 管理员自行创建 ROOT/runtimes/RUNTIME，复制审核后的 runner.py，并准备 PYTHON venv。
python scripts/native_release.py approve-runtime --project-root ROOT --expected-project-root ROOT \
  --runtime-id RUNTIME --python PYTHON --runner-sha256 REVIEWED_RUNNER_SHA
# Windows base Python 方式另加 --site-packages VENV/Lib/site-packages（显式批准的目录）。
python scripts/native_release.py stage --project-root ROOT --expected-project-root ROOT \
  --release-id VERSION --runtime-id RUNTIME --bundle ROOT/inbox/VERSION.zip \
  --gate ROOT/inbox/full-gate.json --expected-sha256 SHA
python scripts/native_release.py activate --project-root ROOT --expected-project-root ROOT \
  --release-id VERSION --expected-current OLD_VERSION --port 8770 --schema-compatible
```

首次 bootstrap 的 `--expected-current` 为字面量 `NONE`。初始化及批准不会创建 venv、启动服务或接触数据库。与 `scripts/release_package.py` 的 UTF-8 SHA sidecar（含中文 ZIP 文件名）兼容；文件名禁止换行。版本 ID 保持 ASCII 可移植格式。

首次激活前，管理员必须独立准备并核验 `ROOT/shared/config/` 的完整有效配置（含 settings/web/prompts/mcp/agent-tools 及所启用功能的配置）与所需 corpus/data；本工具**不复制、不覆盖、不推断**既有配置或用户数据。runner 强制 `RAG_PROJECT_ROOT=PROJECT_ROOT=ROOT/shared`，覆盖继承的旧 checkout 路径，`cwd` 也是 shared；模块和前端静态文件只从明确选中的 staged `src` 加载。版本包中的 config 是源码默认值，不自动成为生产有效配置；管理员须核对新旧代码与共享配置均兼容。代码 rollback 同样不回滚共享配置、凭据或数据。配置中的绝对/越界路径属于管理员信任边界，部署前必须确认可变路径只位于 shared；不要将数据路径配置到 releases。

## staging / preflight / switch / acceptance

- 接收路径限于受管 inbox 普通文件。严格匹配显式 archive SHA、sidecar 内容、`schema=1/level=full/passed=true` source gate、ZIP 内 manifest 及每个成员 SHA；不允许多余或缺失成员。gate 必须为本地可信协调器产物，不能当作用户自报“已通过”。
- 拒绝绝对/穿越/反斜杠/ADS/Windows设备名路径、symlink/特殊文件、目录条目、重复及大小写冲突成员、加密包、超量条目及压缩炸弹。上限：ZIP 64MiB、总展开256MiB、单成员16MiB、10000源码文件、最大压缩比200。只允许现有 source package 的源码目录/根文件，排除 `.env` 等私密/生成数据。
- 任一失败不会覆盖已有 release。中途写入失败保留 `INCOMPLETE`，不可激活；管理员核查后处理，控制器不会递归删除目录。
- 每次启动前重新验证 staged 文件、manifest 身份、Python 与 runner SHA，固定 argv 为 `PYTHON -B -I runner.py preflight|serve --release-root ... --shared-root ... --release-id ... --source-sha256 ... --nonce ... --port ...`，`shell=False`。不接受任意命令模板/额外 argv。
- 产品 `native_app_runner.py` 实际加载该版本 `create_app()`，强制 production/verify。preflight 运行真实 lifespan：配置失败、DB/schema/账号不满足即非零，不执行 DDL。依赖与 DB 不可用不会被 health mock 代替。
- preflight 通过后持久化事务日志，原子 `os.replace` 发布 `previous.json` 与 `current.json` 各自普通 JSON 文件指针（严格 schema/release_id；symlink、额外字段、越界 ID 和旧无扩展名指针均拒绝），核验旧进程身份后停止，启动候选。切换有短暂停机，不承诺零停机；两个指针与进程不是一个原子事务。
- 接受条件必须同时满足实际 `/health/ready` 的 DB 就绪与 `/health/release` 的 **release_id、source_sha256、随机nonce、实际子进程PID** 全匹配。只访问127.0.0.1，不用代理、不跟随redirect。端口已有旧服务、身份错配、提前退出、持续503、超时都不能接受。
- stop 只需匹配独立进程身份，不依赖 DB ready：DB故障不应阻止安全停止已知进程。PID/nonce/OS birth 不匹配时拒绝 signal；Windows 持有并核验同一 OS process handle，Linux 使用 pidfd，并等待 **OS 进程真正退出**，不能把 listener/health 消失当作退出。平台不支持安全生命周期验证时明确拒绝；不执行任意 service/kill shell 命令。
- 默认 preflight 30s、候选 health/旧进程 stop 15s、**独立 rollback readiness 30s**。`--timeout` 控制候选窗口，`--rollback-timeout` 控制候选清理与旧版本恢复；短候选拒绝窗口不能挤占正常 App 的重新启动预算。可显式设定有界值（preflight 0.2..300s、候选/rollback 0.2..120s）；恢复预算写入 PENDING。独占锁覆盖完整操作。显式 recover 的 `--timeout` 是本次恢复操作预算（0.2..120s），不沿用失败候选的短窗口。SIGTERM/系统强杀等可能留下日志/锁；普通异常与 KeyboardInterrupt 尝试同步补偿。

## 失败恢复与中断边界

候选失败：终止本次直接创建的子进程，确认 OS 已退出后恢复 `current=本次升级前版本`，保留/重新启动旧版本，再验证**旧身份和实际DBready**。只有二者通过才返回 `previous_ready=true`。旧进程仍活着但 DB 不 ready 或身份端点不可用时不重复启动；旧 DB 不可用/端口被未知进程占据时保留 PENDING，并报告恢复未完成；不会为了“成功”杀掉未知 PID或降级数据库。首次 bootstrap 失败没有 previous，仅在候选已确认退出或根本未进入 launch-intent 时恢复为无 current。

```bash
# 管理员先诊断陈旧锁：确认原控制器已退出，而非盲删正在使用的锁。
# 然后显式确认此刻 current（可能是失败的新版本，也可能已经恢复旧指针）：
python scripts/native_release.py recover --project-root ROOT --expected-project-root ROOT \
  --expected-current CURRENT_OBSERVED --timeout 30
```

**明确限制**：启动前先持久化 launch-intent，但启动到实际 PID/nonce/OS birth 写入 PENDING 之间仍存在不可跨OS消除的 journal gap；强杀可能留下未登记进程。旧版本恢复启动也有独立持久化 intent 与 restored_state，避免恢复时重复启动。intent 存在而对应进程状态未知时，**即使 old=NONE、端口尚未监听或探针失败，也必须保留 PENDING 并报恢复未完成**，不能返回 `recovered=true`。recover 不猜 PID，不杀未知进程；管理员核对实际进程及 journal 后处理。已登记但失去健康身份且 OS 仍存活的候选同样不能被自动 signal。每个 JSON/指针有原子替换与 POSIX fsync，但不承诺磁盘故障、电源故障、多用户恶意改写、所有信号窗口或跨两个指针+进程的全局原子性。

## 验证与未验证范围

`tests/test_native_release.py` 真实启动 loopback Python HTTP 旧/新/错误版本：成功切换、503回退并旧ready、身份错配、preflight非零/超时、并发锁、预期路径/版本、篡改SHA、恶意ZIP、KeyboardInterrupt补偿、old=NONE 延迟监听 journal-gap 保留日志并拒绝误杀、旧进程 DB-unready 不重复启动。Linux 另有关闭 listener 后继续存活的对抗 fixture，验证 stop 不把端口关闭当退出（Windows 显式 skip 此 Linux pidfd 用例）。输出公开 proof JSON，原始命令/stdio/exit 留在 `output/product-20261028/release-b/native-release-audit`。

`test_native_release_actual_production_app_upgrade_and_recovery` **仅**在协调器 owned QA 标记与 `127.0.0.1/regression` 下运行：随机表前缀/受限DB角色，真实产品runner+uvicorn+production配置，old→new→坏ready→previous ready；比较前后记录/历史/约束 SHA。它显式准备一次 shared/config，以真实 API 创建 private 元数据、假模型连接（不调用模型）和阶段记录，验证跨版本及失败回退后文件 SHA 不变、继承的错误 PROJECT_ROOT 未被使用、全部 staged 源码 SHA/文件集未被写入数据；不输出凭据。普通本地运行显式 skip 该实库用例，不能视为实库验证通过。

跨平台原子 JSON 指针替换与发布失败保留旧值的实际命令和结果以 audit 为准。未做生产Ubuntu安装、真实systemd接管、管理员依赖安装、生产网络流量、进程树/外部守护器协调或生产数据库恢复演练；不得把隔离QA通过描述为这些部署已验收。


## 无 Docker 的完整发布门禁

`native_qa.py` 普通模式只证明原生 PostgreSQL 上的 pytest、ruff 与独占集群清理，**不是完整发布门禁**。
`--gate-session` 模式在同一原生集群上保留真实 API，再由 `native_gate_client.py` 执行现行全部浏览器、MCP SDK、数据库停启和应用重启场景。`release_gate.py` 仍负责配置、依赖、静态检查、离线契约、源指纹前后稳定和最终 full 报告；任何阶段失败均不可打包，不把部分结果改名为 full。

原生会话须由管理员放进专用无提权账号的系统隔离单元：PrivateNetwork、只读源码/依赖、生产数据/配置/数据库 socket 不可见。仅 QA 工作根可写；使用随机端口、自有 PostgreSQL marker/进程/SQL 身份，绝不连接现有生产集群。不能直接把未隔离的宿主 PostgreSQL 填进测试环境变量。

API 和控制器分别监听会话输出目录的 `api.sock`、`control.sock`。桌面只运行浏览器与 SDK 客户端，通过固定目标、临时本地回环 SSH 转发访问这两个文件 socket；不在服务器开放 QA TCP 端口，不改变防火墙，不把数据库暴露给桌面。转发关闭后测试入口消失。普通用户公网访问仍受原生产 HTTPS、令牌和网络白名单约束，QA 通道不能代替正式访问验收。

操作者创建私有 transport JSON，字段为 `schema/host/port/user/identity_file/known_hosts/expected_host_fingerprint/remote_output`。必须核对实际主机指纹和新会话绝对路径；JSON 不包含密码、私钥正文或任意命令模板。随机 QA control/MCP 令牌只在服务器权限受限文件及客户端内存中，禁止复制到聊天、命令行参数或普通证据日志。

在项目根由获准的操作者运行（`OPERATOR_SESSION_JSON`、`FRESH_GATE_JSON` 是本轮明确选择的绝对路径）：

```text
python scripts/release_gate.py --checks full --backend native --native-session OPERATOR_SESSION_JSON --report FRESH_GATE_JSON
```

原生后端未成功时不回退 Docker。控制通道只有 db-stop、db-start、app-restart、finish 四种动作，带会话身份、顺序、请求幂等及回执校验；观察超时不是进程终止，执行窗口不明时保留证据并停止重试副作用。提前 finish 只允许清理，不算完整测试成功。Windows 专属测试在 Linux 的跳过须逐项记录，不能省略真实 native backup/restore、restricted-role 和失败切换测试。Linux/Python 的实际依赖检查与来源报告也不能冒充带哈希、离线重装验证过的完整依赖锁。
