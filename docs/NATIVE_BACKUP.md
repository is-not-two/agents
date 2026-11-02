# 原生 PostgreSQL 备份与空目标恢复

本工具默认直接运行 `pg_dump` / `pg_restore`，不调用 Docker、不读取 `.env`、不创建或删除数据库、不安装扩展、不提权。旧的 Compose 原地覆盖恢复入口已移除。命令需要安装本机 PostgreSQL CLI 和项目 Python `web` 依赖；缺工具明确失败，不自动下载安装。

## 身份与备份边界

- 显式确认 `--expected-database`、`--expected-role`、`--expected-project rag-tech-doc-retriever`、`--prefix`。连接参数来自进程 `POSTGRES_HOST/PORT/DB/USER/PASSWORD`，实际 database、current_user、session_user 与 catalog OID 再次核验。
- 固定 project 名称加实际 prefix records/versions 列类型与主键，是**结构匹配证据，不是数据库所有权的密码学证明**。操作者还须核对服务器、账号和备份目录；有权执行 `pg_control_system()` 时附加 cluster identifier，缺权限不提权。
- 连接为只读 REPEATABLE READ，catalog 与 `pg_dump --snapshot` 使用同一导出快照。并发数据写入不要求停库，但数据库备份不包含外部持久文件、模型、`data/local`、阶段目录和服务器环境凭据；这些须另行受保护备份。不是跨数据库/文件系统全局快照。
- custom dump、`.sha256`、`.manifest.json` 三文件同目录暂存并 fsync，再以 hardlink 逐一原子无覆盖发布；已有任一目标（含目录或断链）即拒绝。失败只清理本次 inode，绝不清理既有产物。需支持 hardlink 的可信目录；三文件不是断电原子事务，强杀/断电后可能留下不完整组，核查后使用全新文件名重试，不自动删除旧文件。
- dump 校验按 1 MiB 分块，不整包载入内存；恢复会把验证后的字节流复制到临时磁盘，须预留约一份 dump 的额外空间。manifest 限 4 MiB、拒绝任意层级的重复 JSON 字段；SHA sidecar 仅读取精确预期长度加一个字节，文件名拒绝换行及其它控制字符。
- 交给 `pg_restore` 的归档句柄使用无缓冲二进制模式：子进程继承的是 OS 文件偏移，不能只依赖 Python 缓冲流在读头之后的逻辑 `seek(0)`。
- SHA 是完整性校验，不是签名。仅恢复可信管理员产生的归档；PostgreSQL 归档可含 SQL/函数，不应把 SHA 当作不可信文件沙箱。完整数据库含私密会话/记录，备份未额外加密，应保护目录/介质并按需求另行加密；Windows ACL 由操作者配置。密码仅通过子进程 `PGPASSWORD` 环境传递，不在参数或日志打印。

## 备份

先在当前 shell 设置实际 `POSTGRES_*` 环境变量（密码不要写进命令历史或文档），再执行：

```sh
python scripts/database_backup.py backup --file /BACKUP/WORKSPACE.dump \
  --expected-database SOURCE_DB --expected-role SOURCE_ROLE \
  --expected-project rag-tech-doc-retriever --prefix workspace --timeout 300
```

`SOURCE_DB/SOURCE_ROLE` 是需要替换的槽位；实际名称须为小写 PostgreSQL 普通标识符。示例不连接任何已配置生产库。工具与服务器主版本须相同；自定义本机工具路径可用 `--pg-dump /PATH/pg_dump --pg-restore /PATH/pg_restore`，不接受 shell 拼接命令。

## 恢复：先准备独立空库，再预检

管理员在工具外准备**与源库不同名称**的空目标数据库、必要最小权限和源库所需的同版本/同 schema 扩展（含 pgvector），并核对 PostgreSQL 主版本、编码、collation、ctype。工具不会安装扩展，恢复 TOC 排除扩展创建和扩展注释；其它表注释/约束、内容、历史及向量保留，owner/ACL 不恢复。

将当前 shell 的 `POSTGRES_DB/USER/PASSWORD` 切到目标，明确确认其他连接已经退出：

```sh
python scripts/database_backup.py restore --file /BACKUP/WORKSPACE.dump \
  --expected-source-database SOURCE_DB --expected-source-role SOURCE_ROLE \
  --expected-database EMPTY_TARGET_DB --expected-role TARGET_ROLE \
  --expected-project rag-tech-doc-retriever --prefix workspace
```

默认只做预检：检查三文件、SHA、manifest、完整归档 TOC、源身份、目标真实身份、空性、扩展与 locale，**不执行恢复 SQL**。必须确认预检结果与独占维护窗口，再给同一命令添加 `--apply`。

应用只使用 `--single-transaction --exit-on-error --no-owner --no-privileges`，没有 `--clean` / `--create` / 删除原库。目标不能有用户表、视图、序列、非扩展函数/enum/domain、自建 schema、其它客户端连接或另一本工具恢复锁。校验后的归档先复制到匿名临时文件，后续路径替换不能换掉实际恢复字节。

恢复锁只协调本工具；不能阻止不遵守锁的外部客户端，所以空目标必须由操作者独占。恢复 SQL/权限错误会使该次 pg_restore 事务回滚；超时/进程被强杀或返回不明确时，先检查目标状态，不盲目重试或删除任何库。源数据库不作为恢复连接目标。恢复完成应核对内容/历史/向量和约束，再另行配置运行账号权限；不能因 CLI 返回成功就声称应用、远端部署或灾备演练已完成。

若 `pg_restore` 已成功返回，但随后 catalog/表结构核验失败，CLI 返回 **2**，stderr 标记 `NATIVE_RESTORE_COMMITTED_UNVERIFIED`：恢复事务已提交，工具**没有自动回滚**，目标可能已写入，须人工核验，不能当作空库重新执行。一般预检/工具失败返回 1；正常预检/恢复返回 0。

## 本机验证

纯单元测试（无 PostgreSQL/Docker）：

```sh
python -m pytest tests/test_native_backup.py -q -k 'not integration'
```

真实集成测试由现有 `scripts/ci_verify.py` 独占 QA 环境提供 `SHILIE_QA_RUN_ID` 与 `POSTGRES_*`。测试先核对派生容器名、`io.shilie.regression` label、运行状态及 `127.0.0.1:POSTGRES_PORT` 端口映射，再创建/最终删除本轮完整随机 UUID 命名且实际创建成功的独立 source/target/denied 库及角色；所有 fixture 数据连接显式关闭，绝不写 regression 或旧业务库。Windows 没有 pg CLI 时仅**测试适配器**使用已核验容器内缓存 CLI，产品代码不依赖 Docker。集成环境缺失会失败而非静默 skip：

```sh
python -m pytest tests/test_native_backup.py -q -s -k integration
```

真实用例包含编辑后 records/history、vector(4)、普通表注释/约束；比较恢复前后精确内容摘要、源未改变、非空目标拒绝。受限角色有建表权限，但 fixture 专用 CHECK 拒绝其数据导入，验证表创建之后的恢复错误仍回滚到空目标。成功打印不含用户值/凭据/端点的 `NATIVE_BACKUP_PROOF` JSON。此文档是本地工具与验收协议，不代表生产调度、备份保留、异地复制或服务器升级已生效。
