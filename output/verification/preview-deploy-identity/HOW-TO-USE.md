# 8771 测试环境专用部署身份 — 使用手册

状态：**已配置完成并实测通过**（2026-11-04 20:58）。私钥 `C:\Users\lzm\.ssh\shilie_preview_deploy_ed25519` 只在你本机，服务器只装了公钥。

- 正式环境 `https://8.156.81.128:8770`（**本身份碰不到，也不该碰**）
- 测试环境 `https://8.156.81.128:8771`（本身份只作用于它）
- 日常不需要 root 密钥、不需要找我、不需要进服务器终端

---

## 0. 三条命令（最常用）

在本机打开 **PowerShell**，进入脚本目录：

```powershell
cd E:\project\agents\rag-tech-doc-retriever\output\verification\preview-deploy-identity
```

| 想做什么 | 命令 |
|---|---|
| **查测试环境状态** | `.\preview-deploy.ps1 status` |
| **部署本地仓库代码到 8771** | `.\preview-deploy.ps1 build 版本名` → `.\preview-deploy.ps1 upload 包路径` → `.\preview-deploy.ps1 deploy 版本名` |
| **只传一个已有包** | `.\preview-deploy.ps1 upload 路径.tar.gz` → `.\preview-deploy.ps1 deploy 版本名` |

`status` 实测输出（可直接看健康与正式 PID）：

```
unit=active
user=shilie_pvapp
pid=368844
health=200
prod_pid_readonly=225177
```

> `prod_pid_readonly` 只是只读显示正式服务 PID，用来自查「正式没被我动过」，不是操作 8770。

---

## 1. 部署一次完整流程（推荐）

### 第 1 步：打包（从本地仓库 `src/rag_tech_retriever`）

```powershell
.\preview-deploy.ps1 build local-20261104
```

生成 `output\verification\preview-deploy-identity\local-20261104.tar.gz`，顶层目录是 `rag_tech_retriever/`（审查要求，缺了会被拒）。

> 注意：`build` 打的是**本地工作副本**，不会自动包含服务器上才有、未入库的改动（例如之前那个 MiMo 修复）。如果你要保留这类现场修复，别用 `build`，改从服务器现网代码打包（见 §4）。

### 第 2 步：上传

```powershell
.\preview-deploy.ps1 upload "E:\project\agents\rag-tech-doc-retriever\output\verification\preview-deploy-identity\local-20261104.tar.gz"
```

成功回 `UPLOAD_OK bytes=...`。包暂存在服务器 `incoming/pending.tar.gz`，**还没生效**。

### 第 3 步：部署（真正生效）

```powershell
.\preview-deploy.ps1 deploy local-20261104
```

runner 会：审查包 → 备份旧代码到 `previous/` → 停 8771 → 换代码 → 起服务 → 等 `health=200` → 复核正式 8770 PID 未变。任一环节失败**自动回退**并报 `DEPLOY_FAILED`。成功回 `DEPLOY_OK ...`。

### 第 4 步（可选）复核

```powershell
.\preview-deploy.ps1 status
```

或浏览器打开 `https://8.156.81.128:8771`（自签证书，点「高级 → 继续访问」）。

---

## 2. 不用封装脚本，手敲 SSH 也行

```powershell
$K = "C:\Users\lzm\.ssh\shilie_preview_deploy_ed25519"
$O = "-i $K -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"

ssh $O shilie_deploy@8.156.81.128 status
# 用 cmd 的 type 传二进制，别用 PowerShell 管道（PS 5.1 会破坏字节流）
cmd /c "type <包路径> | ssh $O shilie_deploy@8.156.81.128 upload"
ssh $O shilie_deploy@8.156.81.128 "deploy <版本名>"
```

---

## 3. 只允许这三件事（越权会被拒）

gate 白名单：`status` / `upload` / `deploy <name>`。其余全部 `REJECTED`，实测包括：

```
ssh ... "id; whoami; cat /etc/shadow"        → REJECTED
ssh ...                                     → REJECTED（无交互式 shell、无 PTY）
ssh ... "systemctl restart shilie"          → REJECTED（碰 8770）
ssh ... "psql -d shilie_native_20261027"    → REJECTED（碰正式库）
ssh ... "sudo -l"                           → REJECTED
```

`deploy` 的 `<name>` 只接受 `A-Z a-z 0-9 . _ -`（`preview-deploy.ps1` 已本地校验，gate/runner 再各校验一次）。

---

## 4. 部署包的硬性要求（审查不过就一行代码都不换）

runner 逐项检查，任一失败即 `DEPLOY_FAILED` 且线上代码保持原样：

- 顶层必须有 `rag_tech_retriever/` 目录
- **拒绝**路径穿越 `../`、绝对路径 `/etc/...`、含空白字符的成员名
- **拒绝**软链接成员、设备/fifo、setuid/setgid/sticky 位
- gzip 完整、单个普通文件、大小 ≤ 200MB、属主必须是 `shilie_deploy`
- 解包后统一 `0644` 文件 / `0755` 目录，属主 `shilie_pvapp`

实测四类恶意包（traversal / symlink / setuid / absolute）全被拒，且线上代码 sha256 未变。

### 想保留服务器上未入库的现场修复（如 MiMo）
别用 `build`（它取本地 git 工作副本）。在 root 终端就地打现网代码的包，再交给专用身份上传：

```bash
# root 终端（仅打包，不部署）
cd /var/lib/shilie-preview/app/.venv/lib/python3.10/site-packages
tar -czf /tmp/payload.tar.gz rag_tech_retriever
# 把 /tmp/payload.tar.gz 取回本机后：
```

然后 `.\preview-deploy.ps1 upload <取回的路径>` → `deploy <名字>`。
本轮实测就是这样保住 MiMo 修复的（部署前后 `model_connection.py` sha256 都是 `6af1fca2…`）。

---

## 5. 出问题了怎么办

| 现象 | 处理 |
|---|---|
| `REJECTED: 仅允许 status \| upload \| deploy <name>` | 命令写错了，或把 `echo`、分号、额外参数拼进了同一条 SSH 命令。**一条 SSH 只发一个词/一个子命令**。 |
| `This account is currently not available` | 不该出现（shell 已设 `/bin/bash`）。真出现说明配置被改过，找我。 |
| `Permission denied` 且 `/usr/bin` 又变 750 | 找我；脚本已加护栏，正常不会复发。 |
| `DEPLOY_FAILED: 路径越界成员 / 非法成员类型 / 含 setuid 位 / 缺少顶层 rag_tech_retriever/` | 包不合规，按 §4 重打；**线上代码未动**，不用慌。 |
| `deploy` 中途失败 | runner 已自动换回旧代码并重启；再跑一次 `status` 确认 `health=200`。 |
| 想手动回退到某次部署 | root 终端把 `previous/<目录>/site-rag_tech_retriever` 换回 `app/.venv/.../rag_tech_retriever` 并 `systemctl restart shilie-preview`（详见 README §4）。 |
| 部署后页面白屏/接口错 | 先 `status` 看 health；再按上一行回退。 |

---

## 6. 边界（如实说明，别误当"绝对安全"）

- 本身份**拿不到** root shell、任意命令、8770 访问权、正式库访问权、不限命令 sudo；sudoers 精确限制为单一 `runner deploy <name>`。
- **能部署代码 ≠ 零数据风险**：部署进去的代码以 `shilie_pvapp` 运行，该身份本就对测试库 `shilie_preview_20261104` 有受控读写（无 DELETE/TRUNCATE/CREATE）。测试库源自生产副本、非匿名化。本方案限制的是**部署通道**，不是**已运行代码的行为**。
- 每次 status / upload / deploy / 拒绝都写 `/var/log/shilie-preview-deploy.log` 与 journald，可追溯。
- **正式环境晋级仍需你另行明确授权**，本身份与脚本都不具备该能力。

---

## 7. 文件说明

| 文件 | 作用 |
|---|---|
| `preview-deploy.ps1` | 本机 PowerShell 客户端（status / build / upload / deploy），已实测 |
| `HOW-TO-USE.md` | 本手册 |
| `setup-preview-deploy-identity.sh` | 服务器端一键配置脚本（已执行，幂等，一般不用再跑） |
| `README.md` | 完整方案、审查逻辑、回退、实测记录与事故复盘 |
| `_e2e_output.txt` / `_e2e_deploy_output.txt` / `_server_run_output.txt` / `_perm_forensics_output.txt` | 实测证据 |

> 私钥 `C:\Users\lzm\.ssh\shilie_preview_deploy_ed25519` 从不进任何脚本内容、不上传、不进聊天。脚本里只引用它的路径。
