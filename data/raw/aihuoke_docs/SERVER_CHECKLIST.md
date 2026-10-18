# 服务器环境对齐 Checklist

> 开发环境: WSL2 / Ubuntu 24.04.4 / PHP 8.0.30
> 项目: AI Phone System V2.9.0 (ThinkPHP 8 + Workerman)
> 最后更新: 2026-07-26

## 1. 操作系统

| 项目 | 开发环境 (WSL) | 服务器 | 状态 |
|---|---|---|---|
| 发行版 | Ubuntu 24.04.4 LTS | | |
| 架构 | x86_64 | | |
| Kernel | 6.18.33.2-microsoft-standard-WSL2 | | |
| glibc | 2.39 | | |
| 时区 | Asia/Shanghai | | |

## 2. PHP 运行时

| 项目 | 开发环境 | 服务器 | 状态 |
|---|---|---|---|
| PHP 版本 | 8.0.30 (NTS) | | |
| igbinary | 3.2.16 | | |
| Redis 扩展 | 6.3.0 | | |

### 必需 PHP 扩展

```
[ ] bcmath       [ ] ctype        [ ] curl         [ ] dom
[ ] fileinfo     [ ] gd           [ ] iconv        [ ] json
[ ] mbstring     [ ] mysqli       [ ] mysqlnd      [ ] openssl
[ ] pdo_mysql    [ ] pdo_pgsql    [ ] pgsql        [ ] redis
[ ] sockets      [ ] sodium       [ ] zip          [ ] igbinary
```

### php.ini 关键配置

```
[ ] date.timezone = Asia/Shanghai
[ ] memory_limit >= 512M
[ ] upload_max_filesize >= 100M
[ ] post_max_size >= 100M
[ ] max_execution_time >= 300
[ ] expose_php = Off
[ ] disable_functions 包含 passthru,exec,system,shell_exec,popen,proc_open 等
```

## 3. 数据库 & 缓存

| 项目 | 开发环境 | 服务器 | 状态 |
|---|---|---|---|
| MySQL | 8.0.46 | | |
| PostgreSQL | 16.14 | | |
| Redis | 7.0.15 | | |

### 数据库健康检查

```
[ ] MySQL 连接正常 — mysql 命令行可登录
[ ] PostgreSQL 连接正常 — psql 命令行可登录
[ ] pg_vector 扩展已安装 (PostgreSQL)
[ ] zhparser 扩展已安装 (PostgreSQL)
[ ] Redis 连通性 — redis-cli PING 返回 PONG
[ ] php check_pg.php — PostgreSQL + Redis 连通 + 队列状态
[ ] php check_kb.php — KB 知识库数据完整性
```

## 4. Composer & 依赖

| 项目 | 开发环境 | 服务器 | 状态 |
|---|---|---|---|
| Composer 版本 | 2.10.2 (官方 phar) | | |
| composer.lock plugin-api | 2.9.0 | | |
| 安装方式 | 官方 phar (~/.local/bin/composer) | | |
| Composer 镜像 | mirrors.aliyun.com | | |

### 安装步骤

```bash
# 1. 克隆仓库后进入项目目录
cd /path/to/server

# 2. 安装依赖（生产环境）
composer install --no-dev --optimize-autoloader
```

```
[ ] composer install --no-dev --optimize-autoloader 无报错
[ ] vendor 目录权限正确
[ ] composer.lock 与仓库一致 (git diff composer.lock 无输出)
```

### 核心依赖版本 (composer.lock 锁定)

| 包 | 锁定版本 |
|---|---|
| topthink/framework | ^8.0.2 |
| topthink/think-orm | ^3.0 |
| topthink/think-multi-app | ^1.0 |
| workerman/workerman | ^4.2 |
| workerman/channel | ^1.2 |
| w7corp/easywechat | ^6.8 |
| guzzlehttp/guzzle | ^7.9 |
| predis/predis | ^3.0 |
| google/protobuf | ^4.31 |
| nesbot/carbon | 2.54.0 |
| symfony/translation | 4.4.47 |
| alibabacloud/mts-20140618 | 2.1.0 |
| phpoffice/phpspreadsheet | ^1.22 |

## 5. 运行时服务

```
[ ] Workerman 服务已启动 (systemctl is-active cherunbao-workerman)
[ ] 手动任务调度器已启动 (systemctl is-active cherunbao-task-scheduler)
[ ] 自动任务调度器已启动 (systemctl is-active cherunbao-auto-task-scheduler)
[ ] WeChatPad 实时消息服务已启动 (systemctl is-active cherunbao-wechatpad-ws)
[ ] WeChatPad 下线兜底 cron 已部署 (crontab 含 `php think wechatpad:probe --sync`，建议每 5 分钟；logout 回调漏收时同步置本地账号下线)
[ ] RPA 服务可启动 (php start_rpa.php)
[ ] 微信服务可启动 (php start_wechat.php)
[ ] 设备服务可启动 (php start_device.php)
[ ] 队列 worker 运行正常
[ ] WebSocket 端口可达 (2345, 2347, 6489)
```

## 6. 网络 & 防火墙 (Linux 服务器)

```
[ ] nftables egress 规则已部署 (deploy/nftables/apply-egress.sh)
[ ] DNS 解析器地址已加入白名单 (dns_ipv4)
[ ] 数据库/Redis IP 已加入白名单 (private_ipv4)
[ ] 外部 API 域名已加入白名单 (allowed_ipv4)
    - ark.cn-beijing.volces.com (火山引擎 Ark)
    - api.coze.cn (扣子 API)
    - .volces.com (火山引擎全站)
[ ] nft list ruleset 确认 policy drop 生效
```

## 7. 环境变量 (.env)

```
[ ] 基于 .example.env 创建 .env
[ ] APP_DEBUG = false (生产环境)
[ ] DATABASE 各项配置正确 (HOSTNAME, DATABASE, USERNAME, PASSWORD)
[ ] PGSQL 各项配置正确
[ ] REDIS 各项配置正确 (HOST, PORT, PASSWORD, SELECT)
[ ] PROJECT.API_KEY 和 SIGN_KEY 已生成
[ ] PROJECT.DEMO_ENV = false
[ ] ARK.API_KEY 已配置 (如需火山引擎 AI 功能)
[ ] COZE.api_key 已配置 (如需扣子 workflow)
[ ] EGRESS.ENABLED 根据实际情况设置
[ ] WORKERMAN 端口配置与防火墙规则一致
```

## 8. 文件权限

```
[ ] runtime/ 目录可写
[ ] public/uploads/ 目录可写 (如存在)
[ ] public/qrcode/ 目录可写
[ ] uploads/ 目录可写
[ ] vendor/ 目录为只读 (www-data 或其他 web 用户可读)
[ ] .env 文件权限 600，不可被 web 用户读取
[ ] deploy/ 下脚本权限 700
```

## 9. 数据库安装

项目通过 Web 安装界面 `public/install/` 完成数据库初始化：

```
[ ] 访问 http://<服务器IP>/install/ 进入安装向导
[ ] 填写 MySQL 连接信息（host/port/user/password/dbname/prefix）
[ ] 填写 PostgreSQL 连接信息（host/port/user/password/dbname/prefix）
[ ] 填写管理员账号密码
[ ] 安装完成后 install.lock 自动生成于项目根目录
[ ] 安装后自动删除 install 目录入口（安全措施）
```

安装脚本会依次执行：
1. `install.sql` — 基础表结构 (la_ 前缀)
2. `update160.sql` ~ `update299.sql` — 增量更新脚本（全部幂等，含 IF NOT EXISTS）
3. `pg.sql` — PostgreSQL 辅助函数
4. `merge_291_296.sql` — 控制平面相关表合并脚本

```
[ ] 确认 la_config 表中 version 记录为 V2.9.9.260806_Release
[ ] 确认所有 update*.sql 已按序执行完毕
[ ] 确认 pg_vector 扩展下的 kb_embedding 表可读写
```

## 10. 开发环境差异已知问题

| 差异 | 说明 | 影响 |
|---|---|---|
| PHP 8.0 vs 8.2 | 项目 php.ini 指向 8.2.9，WSL 装的是 8.0.30 | **严重** — PHP 8.0 EOL，建议服务器统一用 8.2 |
| Node.js | WSL 通过 Windows interop 访问 D:\Dev\Nodejs，服务器可能没有 | 低 — 仅前端构建时用 |
| Docker | WSL 未直接安装 Docker | 中 — 服务器若用 Docker 部署，需额外验证 |
| nftables | WSL 不支持 nftables，deploy/ 脚本无法测试 | 高 — 出站防火墙仅能在 Linux 服务器验证 |

## 11. 上线前最终验证

```
[ ] php check_pg.php — PostgreSQL + Redis 连通 + 队列状态
[ ] php check_kb.php — KB 知识库数据完整性
[ ] Workerman 进程存活确认 (systemctl status cherunbao-workerman --no-pager)
[ ] 手动任务调度进程存活确认 (systemctl status cherunbao-task-scheduler --no-pager)
[ ] 自动任务调度进程存活确认 (systemctl status cherunbao-auto-task-scheduler --no-pager)
[ ] WeChatPad 实时消息进程存活确认 (systemctl status cherunbao-wechatpad-ws --no-pager)
[ ] 关键 API 接口冒烟测试
[ ] 日志目录有写入权限且无异常错误
[ ] SSL 证书有效期检查 (如适用)
[ ] 备份策略确认
```
