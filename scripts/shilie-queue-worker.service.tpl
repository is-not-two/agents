# 队列 worker 的 systemd 单元模板。
#
# 为什么单独一个进程：编码循环与团队运行都是分钟级任务，挂在 Web 请求上会随连接断开一起消失；
# 独立 worker 才能提供无人值守、重试与死信处理。
#
# 安装：scripts/setup_queue_worker.sh（幂等，会按预览/正式两套分别落位）

[Unit]
Description=Shilie 任务队列 worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=__USER__
Group=__GROUP__
WorkingDirectory=__APP__
EnvironmentFile=__ENV_FILE__
ExecStart=__PYTHON__ __APP__/scripts/queue_worker.py --poll 3 --lease 900
Restart=always
RestartSec=10
# 编码任务本身可能跑十几分钟，停止时要给足时间收尾
TimeoutStopSec=120
KillSignal=SIGTERM

# 与 Web 服务同一套沙箱限制：只允许写 data/local、output、model-cache，
# 不要让 worker 拿到比 Web 服务更大的权限面。
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=__APP__/data/local __APP__/output __APP__/model-cache
InaccessiblePaths=__OPT_SHILIE__

[Install]
WantedBy=multi-user.target
