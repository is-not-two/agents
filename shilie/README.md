# 时列 Vue 重写 · 单用户功能迁移

生产构建使用同源的 `GET / POST / DELETE /api/session` 与现有业务 API；不新建或迁移数据库。登录守卫保留受保护页面的目标路径。分类、模块和面包屑共用一份配置。

## 演示

```sh
npm ci
npm run dev:demo -- --port 5174 --strictPort
```

打开 `http://127.0.0.1:5174/`，点「进入演示」，然后在无侧栏的星轨页点「开始」。工作台才显示侧栏（窄屏为抽屉）。演示不接受真实账号，虚构记录仅在标签页内存暂存、刷新丢失。沿「求职 → 求职流水线 → 松屿实验室」可添加岗位和投递、记录复盘、上传合成 TXT 简历和保存练习；也可以在独立「个人简历」页面查看同一份演示简历。不要使用真实私人文件做演示。

本目录是前端唯一开发入口。旧原生前端和入口已从工作树删除，后端和用户数据保留。旧书签的 hash 兼容规则仍由 Vue 路由处理。

## 生产构建与测试

```sh
npm run build
node scripts/verify-demo.mjs
```

验证脚本需要本地演示服务和项目现有 Playwright 测试环境；可用 `SHILIE_DEMO_URL` 改端口，设置 `SHILIE_DEMO_SCREENSHOTS` 导出截图。生产构建的登录、部分旧链接、DAG 配置、人工审批、复习、协作、任务队列和私密锁定用拦截的合成接口验收，不连接正式服务器。开发模式如要连接已获授权的本地后端，可以通过 `SHILIE_API_ORIGIN` 设置 Vite 代理。

普通 `npm run build` 不包含演示登录或示例数据。正式服务切换独立于本地删除；语音和多用户不属于已交付功能。

如果通过本地 FastAPI 同源访问而不是 Vite，在项目根运行 `./start-web.ps1`，启动前会构建 Vue；如只构建不启动数据库或后端，用 `./start-web.ps1 -BuildOnly`。独立的已有 Python 环境可通过 `-PythonExe` 指定；从 Vite 开发时不需要这些步骤。常规发布包也会自动构建 Vue。

项目根目录的 `python scripts/check_vue_candidate.py` 可离线构建并检查临时 Vue-only wheel，也可用 `python scripts/ci_gate.py --vue-candidate` 随门禁执行。此步骤验证包内 FastAPI 的首页、静态文件和旧入口是否退役，不启动数据库，也不发布产物。
