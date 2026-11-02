# 公开语料隔离与可复现导入

## 边界与选择

比较三案：独立数据库隔离更强，但需第二套账号/连接与迁移；混合文件只改标签不能证明公开来源；本项目选择复用现有 `(namespace, chunk_id)` 主键，独立 `public_docs` 域、文件和受审批包。原 `tech_doc` 不删除、不改名、不重新灌库。**这是文档语料隔离，不是多租户权限系统，也不会把个人工作台变成可匿名公开的网站。**

当前默认仍为 `tech_doc`。修改管理员配置 `config/corpora.yaml` 并重启才能启用另一域；HTTP 参数不能扩大白名单、指定文件或表名。若做公开演示，应使用空白独立工作区及仅公开语料的数据库凭据，不同步原库、个人知识、求职资料或私密备份，保留 HTTPS/令牌保护。生产没有因此更新。

## 来源与内容校验

`config/public-sources.json` 固定 14 份快照：既有 FastAPI / pgvector / Python 公开文档 11 份，以及固定提交的 LangGraph overview / persistence / interrupts 三份官方 MDX。来源 URL、原始 SHA、许可标识和许可原文随包保留。LangGraph 文档来自 [官方 docs 仓库](https://github.com/langchain-ai/docs)，不是本项目猜写的技术教程。

复用 V2-a 的 Markdown 标题解析与 1500 字符兜底，得到 325 个切片。MDX 当普通文本处理，不执行代码、导入或其中的指令。公开审批清单还逐条固定切片的 ID/来源/标题/正文/状态 SHA；把私有文本重标为 public、伪造来源或修改正文都无法通过。审批清单本身属于管理员可信配置，不是自动隐私识别器，更不能由上传文件自我批准。

预制公开包与代码发布分开交付；不把整个 data 目录放进源码包。`build` 需要本地保留的审批快照，只有源码的全新机器可直接安装提供 SHA 的公开包；不要用来源 URL 的“最新内容”冒充既有 SHA。

## 本机生成（项目目录内运行）

以下是 Windows PowerShell 命令。Linux 把解释器改为虚拟环境的 `bin/python`。所有输出均拒绝覆盖不同的已有文件；公开数据目录中不要混放原语料。

```powershell
.\.venv\Scripts\python.exe scripts/public_corpus.py build --output output/public-text.bundle.json
# 核对上一步打印的SHA，以实际值替换 TEXT_SHA。只做本地嵌入，不调用LLM。
.\.venv\Scripts\python.exe scripts/public_corpus.py embed --input output/public-text.bundle.json --sha256 TEXT_SHA --output output/public-vectors.bundle.json
```

嵌入模型必须与审批元数据一致：bge-base-zh-v1.5 / 768 维 / 归一化 / query 不加前缀。没有缓存时模型库可能下载权重；本轮验证显式启用 `HF_HUB_OFFLINE=1` 与 `TRANSFORMERS_OFFLINE=1`，仅使用已有缓存，2 个 CPU 线程，没有下载或付费调用。

## 安装、导出与验证（由操作者审核）

```powershell
# 先核对输入包SHA；仅安装独立公开文本，不批准数据库写入。
.\.venv\Scripts\python.exe scripts/public_corpus.py install-text --input output/public-text.bundle.json --sha256 TEXT_SHA --confirm "安装已审核公开语料，不改原语料"

# 以下只连接当前环境变量指定的数据库，必须先确认不是错误的生产库。
# 表/扩展/维度由管理员预先准备；此命令不执行DDL、DELETE或覆盖不同记录。
.\.venv\Scripts\python.exe scripts/public_corpus.py import --input output/public-vectors.bundle.json --sha256 VECTOR_SHA --confirm "仅新增public_docs，不覆盖删除"
.\.venv\Scripts\python.exe scripts/public_corpus.py export --output output/public-export.bundle.json
```

导入先完整验证包，再在单事务与域级锁中执行 `INSERT ... ON CONFLICT DO NOTHING`；已存在的同文同向量保持不变，不同记录拒绝整批，确认后也不执行覆盖/清库。并发碰撞在提交前复核。文本采用同目录临时文件、fsync 与不覆盖的原子发布；相同包重复安装为 no-op。导出固定只读 `public_docs`，发现污染行即拒绝，不允许请求另一个 namespace。

独立数据库的字符排序可能与 Python 不同。导出按统一的 chunk_id 顺序规范化后计算内容 SHA；向量的 float32/六位小数往返单独验证，不把浮点字节差异当成正文变更。导入/导出不是数据库备份恢复命令，不支持删除旧公开版本；内容升级需要另一次明确审查。

### 仅公开文档的检索策略

```yaml
default: public_docs
allowed: [public_docs]
corpora:
  tech_doc:
    label: 本机技术语料
    path: data/processed/corpus.jsonl
  public_docs:
    label: 公开技术文档
    path: data/public/public_docs.bundle.json
```

保留 tech_doc 的定义不代表授权：不在 allowed 中即拒绝，连原文读取和向量请求都不会执行。网页「技术语料域」只显示服务器给出的选项；选择只存在会话内，刷新恢复服务器默认，不把上次结果换个标签。`installed` 仅表示文本文件存在，不保证向量表/模型已就绪；查询时仍验证全部内容 SHA。

`POST /api/query` 与只读聊天可传 `namespace`；省略则使用服务器默认。工具会话和固定流程使用服务器默认，聊天参数不能覆盖受托 Agent 配置。`search_docs` / `debug_retriever` / `protocol_query` 同样受白名单约束，调试缓存按域分开；MCP 不暴露表名，额外参数明确拒绝，资源快照只读默认域。公开向量失败只回落到同域公开文本，未安装时明确空结果，不偷读原语料。namespace 只选择技术文档，scope=personal/all 仍可能包含当前工作区个人内容，不能把它当作公开工作区授权。

## 已验证与尚未验证

- 本轮本机真实 BGE + CrossEncoder + 随机独占 PostgreSQL，325 行公开向量导入、重复导入、只读导出和独立表恢复，原域哨兵与哈希保持不变；不借用旧源数据库或生产数据库。
- 5 个固定检索探针：LangGraph 中断恢复、thread_id、编排能力、FastAPI 后台任务与 pgvector 检索方式。原始命中、来源、耗时和结果在本轮 semantic-ledger.json，不把五例等同于完整质量评测。
- 2 线程本机实测首问约 21 秒（含模型加载），后四问约 8.7–10.3 秒；这不是 2 GiB 云服务器的性能或内存验收，不据五例计算 p95。默认网页仍用全文检索。服务器模型冷启动/内存、公开部署 top-5 和实际网络入口仍待授权后实测。
- 工程测试覆盖同 ID 跨域、白名单、降级不串域、内容/来源/模型/向量/校验和反例、幂等/污染拒绝、真实数据库、真实 HTTP MCP 与网页切换/转义/390px。最终门禁和源码指纹以本轮 gate.json 为准；子集诊断不替代全量验收。
