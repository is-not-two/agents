# 原生运行：结构核验与管理员迁移分离

## 当前状态

本轮修改的是源码与独占本机 QA；没有连接服务器、重启远端服务、修改原库或续用已关闭的 root 授权。历史原生部署有单独记录，不能把本轮代码验收当成已经上线。Docker 仅用于本机隔离回归，**不是服务器部署依赖**。

比较三案：让应用继续启动DDL会需要owner权限；按SQL报错临时跳过会掩盖结构漂移；选择生产默认且强制 verify，管理员迁移走显式 CLI。local 默认保留自动初始化以兼容开发；也可显式使用 verify。

```text
WORKSPACE_PROFILE=production
WORKSPACE_SCHEMA_MODE=verify
```

生产 `auto` 或未知模式直接阻断启动与配置门禁；验证失败不回退迁移或管理员连接。直接调用 RecordStore.ensure_schema 的脚本也读取同一环境/YAML策略。API lifespan 在生产明确调用 verify_schema，并检查运行账号权限。

## 核验承诺

核验使用 PostgreSQL READ ONLY 事务，只查实际解析出的两表 OID、系统目录和权限，不写测试行、不创建扩展/索引/表。它不是 `SELECT 1`；现有 readiness 仍是连通性探针，不能替代启动核验或真实业务验收。

检查无继承/分区的普通永久表、列/类型/NOT NULL、时间默认值、记录及历史主键、已验证且指向实际记录表的外键，以及完整受管 kind CHECK。只在表达式中出现合法名称不算通过：OR true、额外限制、NOT VALID、旧约束均会拒绝。当前不支持额外列、冲突约束/唯一索引、RLS、用户触发器或重写规则，遇到即要求人工审核，不擅自修复。

生产运行账号必须拥有两表 SELECT/INSERT/UPDATE，但不能是高权限角色、表/schema owner 或其成员，不能拥有 schema/数据库 CREATE、DELETE/TRUNCATE/TRIGGER/REFERENCES，也不能继承服务器文件/命令等高权内置角色。这是项目专用账号，不是通用数据库管理员或只读报表账号。权限检查逐项进行，不把多个权限字符串合并后当作“全部满足”。相关目录/权限函数口径见 [PostgreSQL 16 官方文档](https://www.postgresql.org/docs/16/functions-info.html)。

该检查只证明所核验的当前对象和角色配置，不等于审计了数据库里的所有函数、所有其他账号或整个服务器。连接信息仍由环境提供；有 CREATE/owner 需求的运维动作必须另由管理员执行。

## 管理员操作流程（需操作者明确授权）

以下是**将来升级时由有权操作者审核执行的模板**，本轮没有在生产执行。RELEASE_DIR、DB、PREFIX 是具体环境的紧凑槽位；不要把本机 PowerShell 命令粘到 Ubuntu root shell，也不要在聊天里发送数据库密码。

在 **Ubuntu/Workbench 的项目虚拟环境**，先通过受保护环境文件配置数据库连接。检查默认不迁移：

```sh
RELEASE_DIR/.venv/bin/python RELEASE_DIR/scripts/workspace_schema.py check \
  --expected-database DB --prefix PREFIX
```

管理员先完成可恢复备份并核对数据库、账号、表前缀与发行包 SHA，再显式迁移：

```sh
RELEASE_DIR/.venv/bin/python RELEASE_DIR/scripts/workspace_schema.py migrate \
  --expected-database DB --prefix PREFIX \
  --confirm '仅创建或升级工作台结构，不删除记录'
```

迁移在单事务/项目锁中完成；不删除记录，不重建或灌写向量表，不改账号权限。未知结构不自动 DROP/修列；存在非空记录却缺历史表时拒绝用空历史遮盖丢失。约束验证或最终检查失败会回滚该事务。默认核验3秒、锁等待5秒、迁移60秒，由 config/web.yaml 的 schema_*_timeout_ms 限定，不允许无界或无效值。

随后改回受限运行账号的环境，再检查：

```sh
RELEASE_DIR/.venv/bin/python RELEASE_DIR/scripts/workspace_schema.py check \
  --expected-database DB --prefix PREFIX --runtime-role
```

`--expected-database` 是必填的双重身份核对，不会根据“看起来像本项目”推测目标。CLI 不安装软件、不提权、不创建角色、不删除数据。运行账号的 GRANT/REVOKE 由管理员另行审查，且必须针对本项目独立数据库，不能照搬到另一个项目。

## 发布包边界

scripts/release_package.py 只接受源码指纹一致的 full 门禁报告。ZIP 固定元数据，同源跨时刻字节一致；ZIP/SHA 都拒绝碰撞，暂存完成后以硬链接原子无覆盖发布，失败仅清理本次 inode。支持 UTF-8 输出名，不能覆盖既有校验文件。

输出目录必须可信并支持硬链接；两条路径不是断电原子事务，进程被杀或断电仍可能留下孤立ZIP，应人工核对，不把它当成功发布。源码 ZIP 与数据库备份是两种物品，源码 ROLLBACK.sh 不会恢复生产数据库。原生升级失败切回、数据库备份恢复和锁定依赖将在后续发布批次单独验收，不能从本轮源码包推断已具备。

完整门禁会清除继承的 PYTEST_ADDOPTS，避免诊断的 -k 被误当全量；CI 使用本轮独占临时根的 pytest 目录，不复用已有临时数据。远端 CI/CD、分支保护、生产切换仍需实际配置与新授权。

## 验证范围

本机独占 PostgreSQL 中已按正常与反例分别检查结构、旧kind升级、数据/历史保留、未验证/放宽/收窄约束、错列/主键/外键/默认值、缺历史和RLS；受限 LOGIN 实际以 production 启动，完成保存→编辑→历史→恢复，CREATE/ALTER/DROP/DELETE/TRUNCATE 均返回权限错误42501且原数据/结构不变。

发布器有确定性、并发碰撞、写入/fsync/发布故障、源变化及符号链接反例；不具备Windows符号链接创建权限的局部运行明确skip，最终全量实际结果以本轮 gate.json 为准。100项针对性诊断和原浏览器/SDK/故障恢复通过不替代最终全量。云机运行、生产迁移、真实恢复时间和断电语义未验收。
