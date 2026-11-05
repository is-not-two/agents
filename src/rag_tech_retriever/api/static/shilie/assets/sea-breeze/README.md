# 海风女孩素材槽位

默认不请求任何素材：尚未提供素材时，首页使用本地内联 SVG 风景与人物轮廓。

用户提供素材后，可在本目录放入 `girl-base.webp`、`hair.webp`、`skirt.webp`、`glow.webp`，并在 `motion-config.js` 中设置 `seaBreeze.enabled: true`。未能加载的图层不会隐藏 SVG；只有底图加载成功才隐藏 SVG。

可选静音循环视频放在本目录，文件名例如 `loop.webm` 或 `loop.mp4`；在配置的 `seaBreeze.video` 中填其 `/static/shilie/assets/sea-breeze/` 路径。减少动画或关闭动效时视频暂停。素材文件由用户提供，不下载外部资源。

这些素材目前不存在；启用后仍需在实际发布打包流程中核对目录被包含，并在目标浏览器实测。
