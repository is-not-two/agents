# 8771 测试环境专用部署身份 — 状态检查与交付说明

生成时间：2026-11-04 19:53 (Asia/Taipei)
本轮目标：为 **8771 测试环境**配置一个专用、受限的部署身份，可查状态、可经受控入口部署测试版；
不碰 8770、不给 root shell、不给不限命令 sudo、不删数据。

---

## 0. 一句话结论（历史快照，19:53 网络阻塞时版本）

> **最终结论见 §10.8**：20:58 已完成、全部实测通过——专用密钥可真实 SSH 查状态/部署 8771，越权全被拒；系统权限 755 已恢复；正式 8770 全程未动。以下 §0–§9 与 §10.1–§10.7 为过程记录，含已被纠正的错误判断，保留供追溯。

**本机到服务器的 22 / 8770 / 8771 三个端口全部 TCP DROP（10s 超时），但 ICMP ping 通，
且本机访问 baidu/阿里DNS 正常 —— 是服务器侧对 TCP 的阻断（安全组/fail2ban/防火墙规则变更），
不是本机断网，也不是「服务器宕机」。** 按你的要求「如果也无法直连，不要反复尝试」，
我已停止连接尝试，改为提供可在 **阿里云 Workbench 的 root 终端**整段运行的脚本。

---

## 1. 实测状态（本轮，未假定任何旧结果）

| 检查项 | 方法 | 结果 |
|---|---|---|
| `/slow` 模式开关 | 文件存在性 | OFF |
| 本机专用密钥 | 文件列表 | 存在：`C:\Users\lzm\.ssh\shilie_preview_deploy_ed25519` (+`.pub`)，419B/109B |
| 专用公钥指纹 | `ssh-keygen -lf .pub` | `SHA256:iMd1V1+Tw7lSYYqbuktegr6EOFSOAWtvIXV9LOAfnpI` (ED25519) |
| **ED25519 主机指纹核验** | `ssh-keygen -F 8.156.81.128 -f known_hosts -l` | **`SHA256:kf5k4BoDnFNH9oZD/BZCynrBVRfwq9MJWiKPyASx02E`，与你给定值完全一致 → 服务器身份可信** |
| 本机 → `8.156.81.128:22` | `Test-NetConnection` + 底层 `TcpClient` 5s/10s | **DROPPED** |
| 本机 → `:8770` / `:8771` | 同上 | **DROPPED** |
| 本机 → `223.5.5.5:443`、`www.baidu.com:443` | `TcpClient` | **OPEN**（本机网络正常） |
| 本机 → `8.156.81.128` ICMP | `Test-Connection` | **通**（IP 层活着） |
| 代理设置 | env + `netsh winhttp show proxy` | Direct，无代理劫持 |

对照上午（09:15）那次：当时 22/8770/8771 均 True、root 密钥登录成功、两服务 HTTPS 200。
**现在全 DROP**，所以不能沿用上午结论；这是新增变化，最可能是安全组入站规则被改 / fail2ban 把本机 IP 拉黑
（上午有过一次 publickey 被拒）。**具体原因本机看不到，需你在 Workbench 里看 `ufw status` / 云安全组控制台。**

---

## 2. 设计方案（2 案对比，已选 A）

### 案 A（采用）：force-command + 单一 runner + 精确 sudoers
专用系统用户 `shilie_deploy`（nologin、密码锁定、无管理组）；
`authorized_keys` 用 `restrict,command="/usr/local/sbin/shilie-preview-gate"` 把所有 SSH 调用强制压到一个白名单 gate；
gate 只放行 `status` / `upload` / `deploy <name>` 三种，其余记日志并拒绝；
`deploy` 经**精确到单一脚本+参数形状**的 sudo 规则调用 root runner，runner 内部做包审查、停服换位、健康验证、失败自动回退。
优点：不给 shell、不给任意 sudo、正式环境完全不在可写/可执行范围内、每次操作留痕。
缺点：多一层 gate 脚本；部署包必须自带 `rag_tech_retriever/` 顶层目录（已在说明里写清）。

### 案 B（未采用）：给部署用户一个受限 sudoers 直接跑 systemctl + rsync
实现更短，但 `systemctl`/`rsync`/`cp` 组合面太大，参数注入与路径覆盖风险高，且难以保证「不碰 8770」的硬边界。

**否决「直接给 deploy 用户 app 目录写权限」**：那样部署身份可任意改代码、可写任意文件，无法做包审查、
无法保证旧代码留存、无法审计，且「写入即生效」没有回退闸门。

### 硬边界（脚本强制）
- 只操作 `/var/lib/shilie-preview`、`shilie-preview.service`、`shilie_deploy`、`/var/log/shilie-preview-deploy.log`。
- **绝不**触碰 `shilie.service`(8770)、`/opt/shilie`、`/etc/shilie`、`/var/lib/shilie`、正式库 `shilie_native_20261027`、`/etc/shilie-preview/workspace.env`。
- 部署前记录正式服务 MainPID，部署后复核未变；变了即判失败并回退。
- 不新建数据库备份、不清空/覆盖业务数据、不删 `previous/` 里的旧代码、不动服务器上的另一个项目。
- 正式版晋级**需你另行明确同意**，本轮不含。

---

## 3. 部署包审查（你第 4 点要求）

runner 在解包前逐项检查，任一不过即 `DEPLOY_FAILED` 且**一行代码都不换**：

1. **路径穿越**：`tar -tzf` 列出全部成员，拒绝 `/` 开头、含 `..` 段、以 `..` 结尾、含空白字符的成员名。
2. **软链接**：`tar -tvzf` 首字符只接受 `-`(普通文件)/`d`(目录)+`.*` 权限位；拒绝 `l`/设备/fifo；
   再对解包后的 staging 做一次 `find -type l` 复核（防 tar 里藏链接）。
3. **权限位**：拒绝含 `s`/`S`/`t`/`T`（setuid/setgid/sticky）的成员；解包用
   `--no-same-owner --no-same-permissions --no-overwrite-dir`，随后统一 `0644` 文件 / `0755` 目录，
   最后 `chown shilie_pvapp`。
4. **结构**：必须含顶层 `rag_tech_retriever/`；包 ≤ 200MB；`gzip -t` 完整性；非软链的普通文件；属主必须是 `shilie_deploy`。
5. **release 名**：`^[A-Za-z0-9._-]+$`，拒绝 `.`/`..`/含 `/`，防止拼路径。

### ⚠️ 必须说清的边界（不宣称「零数据风险」）
**能部署代码，就意味着部署进去的代码会以 `shilie_pvapp`（测试应用身份）运行，而该身份本就对测试库
`shilie_preview_20261104` 有受控读写权限（records/versions 的 SELECT/INSERT/UPDATE，无 DELETE/TRUNCATE/CREATE）。**
因此：本方案限制的是**部署通道**，不是**已部署代码的行为**。恶意代码一旦被这个身份加载，仍能读到测试库里的
知识、规划、向量数据。缓解只有三层：① 该库是**生产数据的副本、非匿名**，隔离 ≠ 脱敏；
② 库角色无 DELETE/TRUNCATE/CREATE；③ 强制命令与审计日志让「谁在什么时候部署了什么」可追溯。
**不能宣称「完全没有数据访问风险」**，也不能宣称测试环境里的数据是干净/无敏感信息的。

---

## 4. 失败回退方式

- **部署失败自动回退**：runner 在 `keep=$PREVIOUS/<name>-<ts>/` 保留旧 `site-rag_tech_retriever` 与
  `src-rag_tech_retriever`；停服/换位/启动/健康/正式 PID 任一不符，自动换回旧目录并重启，再报 `DEPLOY_FAILED`。
- **事后人工回退**：`previous/` 下每个 release 都有完整旧包与 `payload.tar.gz`，换回即可：
  ```bash
  systemctl stop shilie-preview
  rm -rf /var/lib/shilie-preview/app/.venv/lib/python3.10/site-packages/rag_tech_retriever
  cp -a /var/lib/shilie-preview/previous/<目录>/site-rag_tech_retriever \
        /var/lib/shilie-preview/app/.venv/lib/python3.10/site-packages/rag_tech_retriever
  chown -R shilie_pvapp:shilie_pvapp /var/lib/shilie-preview/app/.venv/lib/python3.10/site-packages/rag_tech_retriever
  systemctl start shilie-preview
  ```
- **整套配置撤销**（回到配置前状态，业务数据不动）：
  ```bash
  rm -f /etc/sudoers.d/shilie-preview-deploy /usr/local/sbin/shilie-preview-gate \
        /usr/local/sbin/shilie-preview-deploy-runner
  rm -rf /var/lib/shilie-preview/incoming/.ssh
  userdel -r shilie_deploy 2>/dev/null || userdel shilie_deploy
  # previous/ 与日志保留，供审计
  ```

---

## 5. 执行前说明（给 Workbench 操作者）

1. **在哪跑**：阿里云 ECS `8.156.81.128` 的 **Workbench root 终端**（本脚本需要 root 建用户/写 sudoers/起停 unit）。
   整段粘贴 `setup-preview-deploy-identity.sh` 即可，脚本 `set -Eeuo pipefail`，任一步失败即停。
2. **会做什么**：SECTION 1 只读体检 → SECTION 2 前置校验 → SECTION 3 建用户/gate/runner/sudoers/日志
   → SECTION 4 服务器端自测（拒绝用例 + 恶意包 + 正常包走完整 upload→deploy + MiMo 修复 sha256 前后比对 + 正式 PID 复核）。
3. **不会做什么**：不重启/不修改 8770；不连正式库；不删任何业务数据；不新建数据库备份；
   不清理 `previous/`；不动 `/opt/selfstock*` 等另一个项目；不输出/复制/上传**私钥**（脚本里只有公钥，非秘密）。
4. **自测会短暂重启 8771**（约几秒，`stop → 换包 → start → 健康等待`），会打断正在使用测试环境的人，
   建议避开使用时执行。这是「实测部署能力」的必要代价，你已授权测试环境验证。
5. **MiMo 修复保护**：脚本 SECTION 1 先打印 `model_connection.py` 的 sha256；正常部署包是**就地打包当前
   运行中的代码**（含未入库的 `thinking: {"type":"disabled"}` 修复，modified sha 应为
   `6af1fca2cc8a0aa34b9146f2813a04bd18721f372f1d5c953133da08ac534253`）；部署前后比对，
   不一致即判失败并回退。**注意：该修复至今只有 mock 验证，未证明真实 MiMo 模型连接成功。**
6. **执行后请把终端完整输出转给我**（尤其 `sshd -T` 的 `AuthorizedKeysFile` 行、SECTION 4 全部结果、
   `PROD MainPID` 前后值）。若 `AuthorizedKeysFile` 不是默认 `.ssh/authorized_keys`，
   脚本已提示需把公钥放到对应位置——这一步要按输出补，我会据输出给补丁。

---

## 6. 明确「未验证」的内容（不拿计划当实测）

| 项 | 状态 |
|---|---|
| 本机 → 服务器的 TCP 连通 | ❌ 本轮实测 DROP，未恢复；脚本**无法由我直连执行** |
| 服务器当前 8771/8770 服务是否仍健康 | ⚠️ 上午 09:15 为 200，本轮因端口 DROP **未复核**；脚本 SECTION 1 会现场体检 |
| 脚本 SECTION 3/4 的真实执行结果 | ⏳ **未执行**，待你在 Workbench 跑完回传输出 |
| 用本机专用密钥 `ssh -i shilie_preview_deploy_ed25519` 端到端登录/查状态/部署 | ⏳ **未验证**（网络阻塞）。网络恢复后命令见 §7 |
| `sshd` 是否真的从 `/var/lib/shilie-preview/incoming/.ssh/authorized_keys` 读取 | ⚠️ 脚本用 `sshd -T` 输出判定，需看回传结果确认 |
| 部署身份「不能访问正式库」的完整证据 | ⚠️ 脚本测了 gate 层拒绝 `curl 8770` / `psql 正式库`；但该用户无 shell、无 sudo 白名单外命令，属**结构性限制 + 命令层拒绝**，未做「以该用户身份直接跑 psql」的穷尽渗透 |
| 真实 MiMo 模型连接成功 | ❌ 未验证（历史只有 mock：改前失败/改后通过/回滚失败） |
| 端口为何被 DROP 的根因（安全组 vs fail2ban） | ❌ 本机不可见，需 Workbench 内查 `ufw status` / `fail2ban-client status` / 云控制台 |
| 正式环境晋级 | ⛔ 不在本轮，需你另行明确同意 |

---

## 7. 网络恢复后，助手端的端到端验证命令（本机 PowerShell）

```powershell
$KEY = "C:\Users\lzm\.ssh\shilie_preview_deploy_ed25519"
$SSH = "ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 shilie_deploy@8.156.81.128"

# 1) 核验主机指纹（应输出 SHA256:kf5k4BoDnFNH9oZD/BZCynrBVRfwq9MJWiKPyASx02E）
ssh-keygen -F 8.156.81.128 -f $env:USERPROFILE\.ssh\known_hosts -l

# 2) 只查状态（不需要 deploy 包）
& ssh -i $KEY -o IdentitiesOnly=yes shilie_deploy@8.156.81.128 status

# 3) 任意命令 / 要 shell / 碰 8770 —— 都应 REJECTED
& ssh -i $KEY -o IdentitiesOnly=yes shilie_deploy@8.156.81.128 "id; whoami"
& ssh -i $KEY -o IdentitiesOnly=yes shilie_deploy@8.156.81.128            # 应直接被 force-command 拦截，无 shell
& ssh -i $KEY -o IdentitiesOnly=yes shilie_deploy@8.156.81.128 "systemctl restart shilie"

# 4) 部署：先在本地构造包（rag_tech_retriever/ 顶层目录），再 upload → deploy
#    upload 走 stdin：
Get-Content .\payload.tar.gz -Raw -Encoding Byte | `
  & ssh -i $KEY -o IdentitiesOnly=yes shilie_deploy@8.156.81.128 upload
& ssh -i $KEY -o IdentitiesOnly=yes shilie_deploy@8.156.81.128 "deploy <release名>"
#    随后复测 https://8.156.81.128:8771 健康、正式 8770 PID 未变。
```

---

## 8. 本地静态校验（已做，不等于服务器实测）

本轮在本机用 Git Bash 5.3.9 对交付脚本做了纯静态校验，**未连服务器、未执行任何 root 动作**：

| 校验 | 结果 |
|---|---|
| 主脚本 `bash -n setup-preview-deploy-identity.sh` | ✅ `MAIN_SYNTAX_OK`（435 行） |
| 内嵌 gate 抽取后 `bash -n` | ✅ `GATE_SYNTAX_OK`（46 行） |
| 内嵌 runner 抽取后 `bash -n` | ✅ `RUNNER_SYNTAX_OK`（138 行） |
| heredoc 起止配对 | ✅ 4 起 / 4 止 |
| 关键安全项存在性 | ✅ `restrict,command` / `PREVIEW_DEPLOY` / 路径越界 / 符号链接 / setuid / ROLLBACK / prod_pid / MiMo 全部 present |

这只是语法与结构自检；**脚本在服务器上的真实行为仍以 Workbench 回传的 SECTION 4 输出为准**（见 §6 未验证项）。

## 9. 文件清单

| 文件 | 用途 |
|---|---|
| `setup-preview-deploy-identity.sh` | 在 Workbench root 终端执行的一键配置 + 服务器端自测脚本（含回退/审计/包审查） |
| `README.md` | 本说明：实测状态、方案、边界、回退、未验证项、执行前说明、本地静态校验 |

（本地 `C:\Users\lzm\.ssh\shilie_preview_deploy_ed25519` **私钥留在本机，未复制、未上传、未出现在任何文件**。
脚本内嵌的是 `.pub` 公钥，属非秘密信息。）

---

## 10. 追加实测（2026-11-04 20:21–20:58，网络放行后直连执行，最终已完成）

> **20:58 最终结论前置**：§10.4 里我一度判定「750 是服务器既有加固、需用户授权 chmod 才能继续」——**这个判断是错的，是我自己的脚本 bug 造成的**。20:53 只读取证（证据 `_perm_forensics_output.txt`）显示三个目录的 `change` 时间正好是 20:27–20:29，即我跑配置脚本 SECTION 3 的时间；根因是脚本第 142 行 `install -d -m 0750 "$(dirname "$GATE")"`——`install -d -m` 对**已存在目录也会改权限**，我每挪一次 gate 路径就把对应系统目录改成 750，然后被自己造成的现象绕进去误判成「既有加固」。**已修脚本（去掉该行、改为只校验不 chmod）、恢复 755、全流程重跑并通过**。详见 §10.8。以下 §10.1–§10.7 保留当时记录，最终状态以 §10.8 为准。

§0–§9 是 19:53 网络阻塞时写的「方案 + Workbench 备用」版本。**用户放行安全组后，已直连服务器真实执行**，结论如下（本轮推翻了 §6 里多条「未验证」）：

### 10.1 网络与登录
- 安全组 SSH(22) 放行 `125.70.13.156`→本机出口变了；用户放行后 **22 实测 OPEN**，`root` 密钥（`selfstock_8_156_81_128_rsa`）直连成功（主机 `iZ2vchbwwn8g6h5wtgtlttZ`）。
- **第二层 ufw 仍锁着**：`8770/tcp ALLOW IN 125.70.13.156`、`8771/tcp ALLOW IN 125.70.13.156`。但两服务本机 `ss` 都 `0.0.0.0` LISTEN、unit 都 active、`https://127.0.0.1:8770/health` 与 `:8771/health` 都 200 → **服务本身健康，外部 8770/8771 DROP 是 ufw 源 IP 限制**。本任务走 SSH(22)，不受影响。
- 主机指纹现场复核 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` = `SHA256:kf5k4BoDn…ASx02E`，与给定值一致。
- `sshd -T`：`authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2`，默认位置正确。

### 10.2 只读前置（脚本假设全部对上）
`shilie-preview.service` User=`shilie_pvapp`、ExecStart 指向 `/var/lib/shilie-preview`；Python 3.10.12；sudo/runuser/tar/systemctl/curl/mktemp/logger 全齐；4 个健康端点全 200；**MiMo 修复现场确认**：`site-packages` 与 `src` 两处 `model_connection.py` 的 sha256 都是 `6af1fca2cc8a0aa34b9146f2813a04bd18721f372f1d5c953133da08ac534253`（未入 git 但已部署、在跑）；`shilie_deploy` 不存在、无残留配置；正式 PID `225177`；预览库 64 条记录。

### 10.3 脚本真实执行 4 次（证据 `_server_run_output.txt`，SECTION 1/2/3 稳定通过）
- SECTION 1/2/3 全绿：建 `shilie_deploy`(uid 991)、`incoming` 0700 / `previous` 0750、`authorized_keys`(restrict+command)、gate、runner、sudoers(visudo parsed OK)、审计日志。**每次重跑幂等**。
- 修掉两个脚本自身 bug：① `systemctl list-unit-files | grep "^…"` 判存在不可靠 → 改 `systemctl cat`；② gate 路径。
- **`sudo -l -U shilie_deploy` 实测**：规则精确为 `(root) NOPASSWD: /usr/local/sbin/shilie-preview-deploy-runner deploy [A-Za-z0-9._-]*` —— sudoers 设计正确。

### 10.4 真正的硬阻塞（服务器既有系统级权限，非脚本 bug）
SECTION 4 全部失败，逐层诊断（7 轮）后钉死：

| 证据 | 结论 |
|---|---|
| `stat`：`/usr/bin`、`/usr/local/bin`、`/usr/local/sbin` 全 `drwxr-x--- 750 root:root`；`/bin -> /usr/bin` | 非 root 用户**无法执行任何系统二进制** |
| `runuser -u shilie_deploy -- /usr/bin/id` → Permission denied | 连 `id` 都跑不了 |
| `setpriv --reuid=991 --regid=991 --clear-groups` 执行 755 目录里的脚本 → 成功 | 是 `runuser/su` 的 PAM 阻挡，不是路径；但真实 SSH 的 force-command 依赖 login shell |
| 复制 `bash` 到 755 目录作 shell：能跑内建命令，但 `/usr/bin/sudo` → Permission denied，`/root/.bashrc` → Permission denied | 零系统改动方案走不通（sudo 在 750 目录） |
| **专用密钥真实 SSH**：nologin → `This account is currently not available`；改 `/bin/bash` → `/bin/bash: Permission denied` | **force-command / login shell 均无法执行**，端到端登录失败 |

→ **根因：这台机器 `/usr/bin` 等系统目录被设成 750，任何非 root SSH 用户都无法执行 shell/程序**。这是服务器既有的系统级加固（不是本任务引入），脚本挪 gate 路径绕不过（shebang 依赖 `/usr/bin/env`）。**本轮未擅自修改任何系统目录权限**。

### 10.5 当前服务器状态（已复位干净，无半成品风险）
- 诊断残留全清；`shilie_deploy` shell 复位 `nologin`；`/opt/shilie-preview-deploy` 已删。
- SECTION 3 建的正式配置**保留**（gate/runner/sudoers/authorized_keys/日志），但**当前不可用**、未启用任何登录。
- **审计日志 0 字节** → 从未发生任何 gate/status/deploy 动作；`previous/` 无本次新增 → 未部署任何代码；`preview=active`、`prod_pid=225177` 未变；**未碰 8770、未连正式库、未删数据、未建备份**。
- 脚本已加固：SECTION 2 新增 `BIN_DIR_MODE` 前置检查，`/usr/bin<755` 时打印 BLOCKER 说明并 `exit 3`，不留下半可用配置；自测从 `runuser` 改 `setpriv`；本地 `bash -n`（主/gate/runner）全过。

### 10.6 需要你拍板（唯一剩余决策）
要让专用身份真正可用，必须改系统目录权限——**这是系统级改动，超出本轮「测试环境配置」授权，我不擅自做**：

```bash
# root，系统级；影响整机所有非 root 用户，请明确同意后我再执行
chmod 0755 /usr/bin /usr/local/bin /usr/local/sbin
# 然后重跑脚本（幂等）→ 用专用密钥真实 SSH 端到端实测 status/拒绝用例/upload+deploy
```

- **选项 A（推荐）**：授权我执行上面 chmod + 重跑 + 端到端实测（含恶意包拒绝、正常包部署、MiMo 修复不丢、正式 PID 复核）。风险点：`/usr/bin` 从 750 放宽到 755 是全机非 root 可读可执行，需你确认这是可接受的。
- **选项 B**：不改系统权限，改用另一种通道——例如部署身份不建独立 OS 用户，而是复用现有 root SSH 但用 `command=` 强制命令限制（root 能执行系统二进制，无需 750 放宽），安全性由 force-command + sudoers 保证，但「专用低权 OS 身份」这一条要放弃。
- **选项 C**：维持现状，配置留着但不启用；正式晋级仍需另行授权。

### 10.7 更新后的验证状态
| 项 | 之前(§6) | 现在 |
|---|---|---|
| 直连服务器 | ❌ 未连 | ✅ 已连、真实执行 4 次脚本 |
| 脚本 SECTION 1/2/3 | ⏳ 未执行 | ✅ 全绿、幂等、sudoers visudo 通过 |
| SECTION 4 服务器端自测 | ⏳ 未执行 | ❌ 被 750 系统权限阻塞，已定位非脚本 bug |
| 专用密钥端到端登录 | ⏳ 未验证 | ❌ 实测失败（nologin / shell Permission denied），根因明确 |
| 恶意包审查 / 正常包部署 / MiMo 不丢 | ⏳ 未验证 | ❌ 未跑到（被 SECTION 4 前置卡住） |
| 正式 8770 / 数据 | — | ✅ 全程未动，PID 225177 未变 |
| 真实 MiMo 模型连接成功 | ❌ | ❌ 仍未验证（历史仅 mock） |

**证据文件**：`_server_run_output.txt`（第 4 次执行完整输出）。

---

## 10.8 最终实测结果与收尾（2026-11-04 20:53–20:58，已完成，全部通过）

### 事故根因（自我纠错）
只读取证 `_perm_forensics_output.txt`：
```
/usr/bin         change=2026-11-04 20:29:27   birth=2026-09-16
/usr/local/bin   change=2026-11-04 20:29:27   birth=2026-09-16
/usr/local/sbin  change=2026-11-04 20:27:45   birth=2026-09-16
```
变更时间正好是脚本 SECTION 3 执行窗口；birth 是镜像创建时间。元凶是脚本里
`install -d -m 0750 "$(dirname "$GATE")"` —— `install -d -m` 对已存在目录同样会改权限。
gate 先后放在 `/usr/local/sbin` → `/usr/local/bin` → `/usr/bin`，三个目录被依次改成 750。
**不是服务器既有加固，不是别人改的，是我自己改坏的，且我误判了整节结论。**

### 修复动作
1. 脚本删掉那行 `install -d -m 0750 "$(dirname "$GATE")"`，改为只校验目录存在且可遍历、绝不 chmod 系统目录（并写注释钉住）。
2. `chmod 0755 /usr/bin /usr/local/bin /usr/local/sbin` 恢复标准权限 → 实测非 root 可执行 `/usr/bin/id`、`/usr/bin/bash`（`BASH_OK_AS_NONROOT`）。
3. shell 从 `nologin` 改为 `/bin/bash`（nologin 会让 sshd 直接拒登；安全性由 `restrict,command=` 保证，不靠 shell）。
4. 保留 SECTION 2 的 `BIN_DIR_MODE` 前置检查作为护栏（权限不足时 exit 3，防止复发）。

### 专用密钥「真实 SSH」端到端（证据 `_e2e_output.txt`）
| 用例 | 结果 |
|---|---|
| `status` | ✅ `unit=active / user=shilie_pvapp / pid=359771 / health=200 / prod_pid_readonly=225177`，exit 0 |
| 任意命令 `id; whoami; cat /etc/shadow` | ✅ `REJECTED` |
| 空命令 / 要交互式 shell | ✅ `REJECTED`（Pseudo-terminal 未分配） |
| `systemctl restart shilie`（8770） | ✅ `REJECTED` |
| `psql -d shilie_native_20261027`（正式库） | ✅ `REJECTED` |

### 完整 SECTION 4（证据 `_server_run_output.txt`，第 5 次执行）
- 4.1 六类负向全 DENY；4.2 status 正常；
- 4.3 **恶意包四类全被拒**且线上代码 sha256 未变：traversal `../evil_escape.py`、symlink `-> /etc/shadow`、setuid、`/etc/cron.d/evil` 绝对路径；
- 4.4 正常包 `upload`（3,291,857 bytes）→ `deploy verify-current` 真实走完停服/换位/起服/健康/正式 PID 复核链；**MiMo 修复 sha256 部署前后都是 `6af1fca2…` 未丢失**；
- 4.5 `preview=active`、`health=200`、`PROD MainPID 225177→225177`、`previous/` 留有回退副本。

### 专用密钥「真实 SSH」upload→deploy（证据 `_e2e_deploy_output.txt`，最终判据）
```
UPLOAD_OK bytes=3291822  (upload_exit=0)
DEPLOY_OK name=e2e-verify backup=.../previous/e2e-verify-20261104-205711 health=/health  (deploy_exit=0)
health=200  mimo_sha=6af1fca2…  prod_pid=225177  records=64  preview=active
```
→ **专用密钥确实能查询、能部署 8771，且拿不到 shell、碰不到 8770/正式库。**

### 收尾（干净）
- 删除本轮两个纯验证回退目录（`verify-current-*` / `e2e-verify-*`，内容=当前运行代码副本，非业务数据）；保留 `app-native-*` 真实历史部署。
- 删除 `incoming/e2e-payload.tar.gz` 与本机临时包；`incoming` 只剩 `.ssh/` 与 `.cache/`。
- 系统目录 755、`shilie_deploy` shell `/bin/bash`、审计日志 29 行（真实记录了 status/upload/deploy/拒绝）。
- **正式 8770 PID 225177 未变、正式库未连接、数据 64 条未变、未建备份、未删业务数据。**
- 正式版晋级仍需用户另行明确授权。

### 最终验证状态（覆盖 §10.7）
| 项 | 最终 |
|---|---|
| 直连 / 脚本 SECTION 1–3 | ✅ 通过、幂等 |
| 专用密钥真实登录 / 查状态 / 拒绝越权 | ✅ 5/5 通过 |
| 恶意包审查（4 类） | ✅ 全拒、线上代码未动 |
| 正常包 upload→deploy（专用密钥真实 SSH） | ✅ 通过 |
| MiMo 修复不丢 | ✅ sha256 前后一致 |
| 测试服务健康 / 正式未动 / 数据未变 | ✅ 200 / PID 225177 / 64 条 |
| 真实 MiMo 模型连接成功 | ❌ **仍未验证**（历史仅 mock） |
| 正式环境晋级 | ⛔ 需另行明确授权 |

### 日常使用（本机 PowerShell）
```powershell
$K = "C:\Users\lzm\.ssh\shilie_preview_deploy_ed25519"
$O = "-i $K -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"
ssh $O shilie_deploy@8.156.81.128 status                    # 查状态
Get-Content .\payload.tar.gz -Encoding Byte -Raw | ssh $O shilie_deploy@8.156.81.128 upload   # 上传包
ssh $O shilie_deploy@8.156.81.128 "deploy <release名>"      # 部署（包须含顶层 rag_tech_retriever/）
```
部署包审查、回退方式、数据访问风险边界见 §3 / §4（**能部署代码 ≠ 零数据风险**，部署的代码以 `shilie_pvapp` 运行，仍可读测试库；不宣称无风险）。

