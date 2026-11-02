# RELEASE-B：离线运行时溯源与 Linux CPU 锁定路线

## 已实现的边界

`scripts/release_provenance.py` 支持 Python **3.10+**：3.11+ 使用标准库
`tomllib`，3.10 使用 `web`/`dev` extra 声明的条件依赖
`tomli>=2.0.1,<3; python_version<'3.11'`。不提升应用的 Python >=3.10 约束，
不扩大原有元数据文件字节上限；两个解析器均不可用时明确报缺少 extra 的错误。
官方依据：[Python tomllib（3.11 新增）](https://docs.python.org/3/library/tomllib.html)、
[Tomli 官方兼容层](https://pypi.org/project/tomli/#building-a-tomli-tomllib-compatibility-layer)、
[Tomli 2.0.1 loads 接口](https://pypi.org/project/tomli/2.0.1/)。
它不导入应用、不联网、
不安装/升级依赖、不调用 pip/Docker/数据库、不读取环境变量、`.env`、
`direct_url.json`、可执行文件路径或整台机器的包清单。默认只输出 JSON 到 stdout，
**不写文件、不扫描模型目录**。

本轮选择：直接 `pip freeze` 会包含无关包/私有来源且不是跨平台锁；立即解析 Linux 锁
需要明确目标环境和实际构建；先提供可复核本机溯源与分开的 Linux 构建验收路线。
**provenance ≠ lock；Windows 已安装版本清单不能称 Linux CPU 锁。**

报告字段固定为 `schema=rag-tech-doc-retriever/release-provenance`、`version=1`、
`content`、`content_sha256`，可选独立的 `observed_at_utc`。摘要是
`SHA256(UTF-8 JSON(content, sort_keys=True, separators=(",",":"), ensure_ascii=False))`，
不含时间、绝对路径、用户名或主机名。相同观测内容得到相同摘要；它不是签名或真实性证明。

`content` 包含：

- Python 完整版本、实现、OS/内核发行版本、CPU 架构；不声称 CPU 指令集、CUDA 或 ABI 已验收。
- `pyproject.toml` **原始字节** SHA256、项目公开名称/版本。
- 只查询 pyproject 基础依赖、选中 extra 和项目本身的分发名称/已安装版本；默认 extra 为
  `web`（存在时），`--extra web --extra rag` 可显式扩大。未安装为 `installed:false,version:null`。
  不解析依赖 URL，不输出需求原文；**不枚举传递依赖、不求解/求值环境标记**，不是完整 SBOM/锁。
- 数据库默认 `not_observed`；仅 `--db-image-digest sha256:<64位小写十六进制>` 接收操作者声明，
  `verification=operator_declared_not_runtime_verified`。镜像标签、仓库引用与短 SHA 均拒绝；
  该输入不证明本地或生产实际运行了该镜像。多架构 index digest 与平台 manifest digest
  也须由后续部署验收区分，工具不会猜测。
- 模型三态：未请求、manifest 声明、显式文件字节实测，绝不把 filemtime 当 SHA。
- `reproducibility.classification=provenance_not_lock`、
  `linux_cpu_lock=not_built_or_validated`、`transitive_dependencies_locked=false`。

## 本机用法（不联网）

在项目根运行（stdout 为原生 JSON，错误写 stderr，退出码：0 成功、2 校验失败、3 I/O失败）：

```powershell
.\.venv\Scripts\python.exe scripts/release_provenance.py
.\.venv\Scripts\python.exe scripts/release_provenance.py --extra web --extra rag --timestamp
# 父目录需已存在；只创建项目内的新 .json，任何现存文件拒绝覆盖。
.\.venv\Scripts\python.exe scripts/release_provenance.py --output output/provenance-001.json
.\.venv\Scripts\python.exe -m pytest tests/test_release_provenance.py -q
```

显式 `--output` 拒绝项目外路径、symlink/junction/reparse 路径、覆盖、非 `.json` 和缺失父目录；
O_EXCL 创建，失败尽量只删除本次拥有的残片。**输出目录与输入文件必须由本机可信操作者控制**：
本工具不是抵御拥有并发文件系统写权限攻击者的隔离沙箱；Windows 无完整 `openat`/目录句柄链。
默认 stdout 不受输出目录写入竞态影响。stdout JSON 与显式文件内容等价。

### 模型：不自动遍历，不自动发现缓存，不宣称完整模型

默认总上限 64 MiB、最多 128 个显式文件；可显式调高 `--model-max-bytes`，硬上限 16 GiB。
大权重需操作者明确选择并接受本机 I/O 成本，未选择的权重不会被打开。
仅允许常见模型/分词器固定文件名与权重分片名，目录只允许 `1_Pooling` 等数字+已知模块名
（最多两层）。拒绝 `.env`/任意 JSON/凭据文件名、绝对路径、`..`、反斜线别名、重复路径、
symlink/junction/reparse 点及硬链接文件。读取前后检查文件身份/大小/mtime，SHA 始终来自字节。
白名单不是内容秘密扫描器：操作者不能将凭据复制到允许的模型文件名下再要求采集。

```powershell
# 小配置实测，不代表未列出权重或整个目录的完整性。
.\.venv\Scripts\python.exe scripts/release_provenance.py `
  --model-root MODEL_ROOT --model-file config.json --model-file 1_Pooling/config.json
# 权重仅在明确选择/调高总字节预算后读取：
.\.venv\Scripts\python.exe scripts/release_provenance.py `
  --model-root MODEL_ROOT --model-file model.safetensors --model-max-bytes 1073741824
```

实测模式为 `selected_bytes_hashed_not_full_model`，路径只输出相对文件名。
manifest 模式只验证清单结构、白名单、数量/字节上限、SHA 格式，不打开模型文件，始终标记
`declared_not_verified`；额外字段拒绝，防把任意 secret/URL 搬入报告：

```json
{
  "schema": "rag-tech-doc-retriever/model-hashes",
  "version": 1,
  "files": [
    {"path": "config.json", "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "size_bytes": 123}
  ]
}
```

以上 `a` 哈希只是格式示例，**不是任何实际模型的摘要**。使用
`--model-manifest MODEL_MANIFEST.json`，不得同时使用 `--model-root/--model-file`。
清单摘要是原始清单字节 SHA；`selection_sha256` 是排序后的文件条目规范 JSON 摘要。
模型代码、许可证/来源与恶意 pickle 权重安全性不由本工具验证；不要启用不可信 remote code。

## 尚未完成：可复用 Linux CPU lock + wheelhouse

当前仅实现并局部验证上述离线工具。**没有实际 Linux 构建、没有本批 CPU lock、
没有完整 wheelhouse、没有 Linux 安装/启动验收**；本机 Windows 包版本只能作选择候选的证据。
不能把 `pip freeze` 重命名为 `requirements-linux.txt` 冒称完成。

建议目标先冻结为 **Linux amd64 / CPython 3.12 / CPU-only**。另一架构/Python minor 必须
独立锁与 wheelhouse，不能共用。后续授权联网/构建时，使用独立的 Linux 构建环境：

1. 将源码发布包 SHA、实际 Python/base-image 的平台 digest、pip 与锁工具版本、index 来源策略
   固定为受审输入；禁止在 lock 中放带凭据 URL。工具链的锁和应用锁分开。
2. `web` 与 `web+rag` 分 profile。CPU PyTorch wheel 按官方 CPU wheel 来源显式固定；不要给
   所有包盲目追加 `--extra-index-url`（依赖混淆风险）。将审核过的 CPU wheel 下载到本地源，
   由专用、可信 index/本地 wheelhouse 解析；确认 wheel tag/版本确实为目标 CPU 构建。
3. 在**实际目标 Linux** 解析所有传递依赖和标记，生成逐包精确版本+SHA256的 hash lock；
   为项目本身构建 wheel 并保存其 SHA/构建源码 SHA。不得仅对照本机 Windows 版本。
4. 下载/构建全部 wheels 到平台专属 wheelhouse，记录每个 wheel 的文件 SHA 与许可；
   若依赖没有目标 wheel，明确失败或单独审计源码构建，不偷偷在线编译。
5. 复制到第二个全新、关闭网络的 Linux 运行环境，执行下列**待验证命令模板**，保留 stdout/
   stderr/退出状态。离线导入成功仍不等于实际 RAG、PostgreSQL、模型字节与资源预算已验收。

```sh
# 以下为未来 Linux 构建操作，不是本轮已执行结果；LOCK/WHEELHOUSE/APP_WHEEL 为审计输入。
# 由单独受控工具环境提供固定版本的 pip-tools：
python -m piptools compile --extra web --generate-hashes --resolver backtracking \
  --output-file LOCK pyproject.toml
# 若做 rag profile：另用 --extra web --extra rag，先落实上面的 CPU wheel 来源策略。
python -m pip download --require-hashes --only-binary=:all: --dest WHEELHOUSE -r LOCK
# 源码发布包应在受控/已锁构建工具环境先产出 APP_WHEEL；本命令不联网装构建工具。
python -m pip wheel --no-deps --no-build-isolation --wheel-dir WHEELHOUSE .
# 在另一个全新、禁网 Linux venv 中，前提：pip 本身与目标 ABI 已审核。
python -m pip install --no-index --find-links WHEELHOUSE --require-hashes -r LOCK
# 项目自身的wheel及SHA另行加入发布安装锁，再执行同样的require-hashes安装；
# 不用“pip install APP_WHEEL”绕过摘要约束。
python -m pip check
python -c "import fastapi, uvicorn, cryptography, psycopg2, langgraph, mcp, jsonschema, yaml"
python scripts/release_provenance.py --extra web --output output/linux-provenance-001.json
```

`LOCK/WHEELHOUSE` 必须替换为受审平台目录；第二环境用 OS/容器层禁网，不把 `--no-index`
当成禁止 direct URL 网络访问的隔离措施。审计 lock 中不得含 direct URL/VCS/editable 或未锁条目。
应用安装锁需同时纳入项目 wheel 的精确版本和SHA，确保最后一步不是绕过 hash gate。
待获得上述证据后才能在独立交付记录中宣称 Linux CPU 可复现；本工具的保守状态不自动升级。
