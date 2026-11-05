# 8771 运行代码同步发布

- 本地权威发布分支：codex/shilie-release-convergence-20261105。
- 同步源码目录：E:/project/agents/rag-tech-doc-retriever/output/verification/release-convergence-20261105/deploy-sync-20261105/source。
- 部署目标：https://8.156.81.128:8771；正式 8770 不在本次范围。
- 所有运行包文件从同一提交导出；生成 release-sync.json 后，将同一包部署到服务器 site-packages 与 src 两处。服务器环境配置、依赖与数据库继续使用现有隔离环境，不用本机内容反向覆盖。
- 原开发 checkout 含未提交修改，保留不覆盖，不能再用旧的 preview-deploy.ps1 build 从该目录随手发布。后续变更应在上述权威版本基础上进行。
- 本次保留服务器三个额外 v2 演练文件并升级 v118，保留 MiMo 修复、私密状态重试及备份密文预检。测试数据不是生产数据的替代物；不把测试版自动推到 8770。
- 发布回执、逐文件清单、源提交、包 SHA256、健康检查和字节核对在同步目录上层 deployment.json；记录成功才表示部署完成。
- 自签 IP HTTPS 仍不是受信任公有证书。本轮 SSH 固定服务器指纹，不关闭 SSH 主机校验；不能将浏览器或 urllib 忽略自签 HTTPS 警告称为已验证 TLS 身份。
