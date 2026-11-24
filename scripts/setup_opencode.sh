#!/bin/sh
# 一键准备 opencode 运行环境（幂等）：二进制 + 配置 + 监督脚本。
#
# 为什么要有这个脚本：opencode 的二进制和配置原本散在 /tmp 和手工步骤里，
# 机器重启就没了。这里把「装什么、放哪、权限多少」固化下来。
#
# 用法：setup_opencode.sh [--binary-url URL]
set -eu

ROOT=${ROOT:-/opt/shilie}
# 注意：/opt/shilie/preview 被 drop-in 改名过，真实预览目录在 /var/lib。
APP=${APP:-/var/lib/shilie-preview/app}
OC_HOME=$ROOT/opencode-home
OC_BIN=$ROOT/opencode/opencode
VERSION=${VERSION:-1.19.5}

echo "== 1/4 二进制 =="
if [ -x "$OC_BIN" ]; then
  echo "已存在：$("$OC_BIN" --version)"
else
  mkdir -p "$ROOT/opencode"
  url="https://github.com/anomalyco/opencode/releases/download/v$VERSION/opencode-linux-x64.tar.gz"
  echo "下载 $url"
  curl -fL --retry 3 -o "$ROOT/opencode/oc.tar.gz" "$url"
  tar -xzf "$ROOT/opencode/oc.tar.gz" -C "$ROOT/opencode"
  rm -f "$ROOT/opencode/oc.tar.gz"
  echo "已安装：$("$OC_BIN" --version)"
fi

echo "== 2/4 配置（模型指向工作台的连接） =="
mkdir -p "$OC_HOME/.config/opencode"
"$APP/.venv312/bin/python" - "$APP" "$OC_HOME" <<'PY'
import json, pathlib, sys
app, home = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
cfg = json.loads((app / "data/local/llm-connection.json").read_text(encoding="utf-8"))
conf = {
    "model": "openai/" + cfg["model"],
    "provider": {"openai": {"options": {"baseURL": cfg["base_url"], "apiKey": cfg["api_key"]},
                            "models": {cfg["model"]: {"name": cfg["model"]}}}},
    # 编辑放行；命令只放行测试与只读命令，其余拒绝（无人值守时没人点“允许”）。
    "permission": {"edit": "allow", "webfetch": "deny",
                   "bash": {"*": "deny", "python*": "allow", "ls*": "allow", "cat*": "allow"}},
}
target = home / ".config/opencode/opencode.json"
target.write_text(json.dumps(conf, ensure_ascii=False, indent=2), encoding="utf-8")
target.chmod(0o600)
print("写入", target, "model:", conf["model"])
PY
chmod 700 "$OC_HOME"

echo "== 3/4 监督脚本 =="
chmod +x "$APP/scripts/opencode_supervisor.sh"
echo "就绪：$APP/scripts/opencode_supervisor.sh"

echo "== 4/4 自检 =="
"$OC_BIN" --version
echo "HOME=$OC_HOME"
echo "配置：$(ls -l "$OC_HOME/.config/opencode/opencode.json" | awk '{print $1, $5"B"}')"
