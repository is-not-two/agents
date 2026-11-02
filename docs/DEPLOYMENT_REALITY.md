# 服务器部署实况与切换规程（2026-11-02 实测）

> 本文记录 `8.156.81.128` 的真实部署拓扑与本次 v85→v100 升级中踩到的全部坑。
> 与 `docs/NATIVE_RELEASE.md` 的差异在于：那份描述的是「设计意图」，本文是「磁盘实况」。

## 1. 真实拓扑（与设计文档不一致的部分）

| 项 | 实际情况 |
|---|---|
| 主机 | `8.156.81.128`，`root`，密钥 `~/.ssh/selfstock_8_156_81_128_rsa` |
| 服务 | systemd `shilie.service`，`User=shilie`，`Type=simple` |
| 端口 | 8770 HTTPS（自签证书 `/etc/shilie/server.key|crt`） |
| **代码实际来源** | **`/opt/shilie/current`（软链）→ `RAG_PROJECT_ROOT`** |
| **包实际来源** | **`.venv/lib/python3.10/site-packages/rag_tech_retriever`（非 editable）** |
| 数据与配置 | `/var/lib/shilie/data`、`/var/lib/shilie/config`（曾是独立副本，已迁入 release） |
| 模型缓存 | `/var/cache/shilie/huggingface`（1.5G，含 bge-base-zh-v1.5 与 bge-reranker-base） |
| 数据库 | `shilie_native_20261027`，用户 `shilie_app` |

### 关键纠正：历史上所有 `current` 切换都未真正生效

`/etc/systemd/system/shilie.service.d/workspace.conf` 曾包含：

```ini
[Service]
Environment=RAG_PROJECT_ROOT=/var/lib/shilie
```

drop-in 优先级高于主 unit 的 `Environment=RAG_PROJECT_ROOT=/opt/shilie/current`，
因此**服务一直读取 `/var/lib/shilie` 里的代码副本**，而不是软链指向的 release。
`native-20261031-ec488419`（v92）虽然已同步到 `/opt/shilie/releases/`，但从未真正上线。

**2026-11-02 已删除该 drop-in**，恢复标准路径。删除前备份在
`/var/backups/shilie/dropin-<stamp>/workspace.conf`。

### 关键纠正：改 `src/` 不生效

包以非 editable 方式安装，运行时 import 走 `site-packages`。
**部署必须同时覆盖 `site-packages/rag_tech_retriever`**，否则页面版本号不变。

## 2. 表结构不兼容（本次唯一的功能阻障）

新代码 `RECORD_KINDS` 有 17 种，数据库 CHECK 约束原有 8 种：

```
缺失 9 种：job_lead application interview_report resume_version
           learning_card learning_review notification_outbox
           agent_memory agent_session
```

`WORKSPACE_SCHEMA_MODE=verify` 在启动时调用 `verify_workspace_schema()`，
`managed_kind_check()` 逐 token 比对表达式，不匹配即抛
`StorageError: 工作台kind约束未完整迁移或未验证`，**服务拒绝启动**。

这是设计意图（宁可拒绝启动也不静默出错），本次按用户授权重建约束：

```sql
BEGIN;
ALTER TABLE workspace_records DROP CONSTRAINT IF EXISTS workspace_records_kind_check;
ALTER TABLE workspace_records ADD CONSTRAINT workspace_records_kind_check
  CHECK (kind = ANY (ARRAY[
    'knowledge','plan','agent_profile','workflow','workflow_run','lesson','wish','diary',
    'job_lead','application','interview_report','resume_version',
    'learning_card','learning_review','notification_outbox',
    'agent_memory','agent_session']));
COMMIT;
```

约束表达式必须是 `kind = ANY (ARRAY['...'::text, ...])` 的规范形，
否则 `managed_kind_check` 会拒绝（它校验的是表达式结构，不是「包含所有词」）。

## 3. 标准切换规程（已验证）

```sh
# 1. 本地：从 git HEAD 打包，排除运行产物
git -c core.quotepath=false archive --format=zip --output=rel.zip HEAD
# 解压后删除 output/stages、output/playwright、output/web（体积大且可重生成）

# 2. 上传
scp -i ~/.ssh/selfstock_8_156_81_128_rsa rel.tar.gz root@HOST:/opt/shilie/incoming/

# 3. 服务器：解包到新 release
tar -xzf /opt/shilie/incoming/REL.tar.gz -C /opt/shilie/releases/REL
cp -a /opt/shilie/releases/<上一版>/.venv /opt/shilie/releases/REL/.venv   # 复用 venv
chown -R root:shilie /opt/shilie/releases/REL

# 4. 迁移生产配置与用户数据（生产值优先）
cp -a /var/lib/shilie/config/*.yaml /opt/shilie/releases/REL/config/
cp -a /var/lib/shilie/data/local/. /opt/shilie/releases/REL/data/local/

# 5. 切换
ln -sfn /opt/shilie/releases/REL /opt/shilie/current
systemctl restart shilie

# 6. 覆盖 site-packages（关键！否则代码不生效）
SITE=/opt/shilie/releases/REL/.venv/lib/python3.10/site-packages
rm -rf $SITE/rag_tech_retriever
cp -a /opt/shilie/releases/REL/src/rag_tech_retriever $SITE/rag_tech_retriever
chown -R root:shilie $SITE/rag_tech_retriever
systemctl restart shilie
```

## 4. 回滚

```sh
# 只回滚代码（不动数据库）
ln -sfn /opt/shilie/releases/<上一版> /opt/shilie/current
SITE=/opt/shilie/releases/<上一版>/.venv/lib/python3.10/site-packages
rm -rf $SITE/rag_tech_retriever
cp -a /var/backups/shilie/site-pkg-<stamp> $SITE/rag_tech_retriever
systemctl restart shilie

# 回滚数据库（仅当本次做过结构变更）
sudo -u postgres pg_restore -d shilie_native_20261027 -c /var/backups/shilie/pre-switch-*/db.dump
```

注意：**数据库约束变更不可通过软链回滚**。若新版加了 kind，回退到旧代码会因
「约束包含多余 kind」而失败（`managed_kind_check` 要求数量相等）。回滚前须一并恢复旧约束。

## 5. 本次升级验收记录（2026-11-02）

| 检查项 | 结果 |
|---|---|
| 服务状态 | active |
| 健康检查 | `{"status":"ok","storage":"PostgreSQL"}` |
| 线上静态版本 | **v100**（v85 → v100） |
| `evaluation.js` | HTTP 200 |
| `/api/eval/questions` | 200（带 token）/ 401（无 token） |
| 记录数 | 15（升级前后一致） |
| 向量数 | 494 = tech_doc 237 + python_docs 257（一致） |
| 评测·重排开 | top-1 90% / top-3 100% / top-5 **100%**，6 题上移，Q08 #7→#1 |
| 评测·重排关 | top-1 40% / top-3 60% / top-5 **90%** |
| 启动错误 | 无 |

评测耗时：重排全量约 **250 秒**（10 题 × 候选池 20，CPU 单线程）。

## 6. 备份清单

| 位置 | 内容 |
|---|---|
| `/var/backups/shilie/pre-switch-20261102-111913/db.dump` | 升级前数据库完整 dump |
| `/var/backups/shilie/rootfix-20261102-112609/` | 迁移前的 data 与 config |
| `/var/backups/shilie/site-pkg2-20261102-112650/` | 覆盖前的 site-packages 包 |
| `/var/backups/shilie/dropin-<stamp>/` | 删除前的 systemd drop-in |
| `/var/backups/shilie/codeswap-20261102-112117/` | 中途回滚用的 src 备份 |
