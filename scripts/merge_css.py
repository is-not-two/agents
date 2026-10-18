"""把 base/demo/tree/automation 四个样式表合并为单一 app.css。

设计取舍：只做机械拼接，不做规则去重或属性合并。

为什么不去重：CSS 的层叠结果由「规则出现的先后顺序」决定，而非选择器是否重复。
本项目多处存在有意的层叠——例如 .topbar 在 base.css 里定义了两次
（主样式 + 移动端微调），.tree-viewport 先定义 height:520px 再被后续覆盖。
一旦按选择器去重或按属性合并，这些顺序语义就会被破坏。实测记录：
  · 按选择器去重 → .tree-viewport 的 overflow:auto 被整体删除，
    390px 视口出现横向滚动；
  · 按属性合并 → :root 的 font-family 被丢弃，页面回退 Times New Roman，
    且半透明顶栏背景覆盖了用户要求的纯黑。

机械拼接的代价是文件体积（约 61KB），换来的是渲染结果与合并前逐属性一致，
可用浏览器计算样式 diff 严格验证。体积在本地应用可接受；
若将来需要瘦身，应在具备完整回归验证手段的前提下单独处理。
"""

FILES = ['base.css', 'demo.css', 'tree.css', 'automation.css']
LABELS = {
    'base.css': '基础与布局',
    'demo.css': '内容与组件',
    'tree.css': '规划树与视觉',
    'automation.css': '自动化',
}

HEAD = ('/* 时列样式：单一入口。\n'
        '   由 base.css / demo.css / tree.css / automation.css 机械拼接而成，\n'
        '   规则顺序与合并前完全一致，因此渲染结果逐属性相同。\n'
        '   不要在此文件内做跨区去重或属性合并——同文件内的重复定义是有意的层叠。\n'
        '   原始文件已移出页面加载，仅作归档参考；重新生成见 scripts/merge_css.py。 */\n')

parts = [HEAD]
total = 0
for name in FILES:
    src = open(name, encoding='utf-8').read()
    total += len(src)
    parts.append('\n/* ==================== %s（原 %s） ==================== */\n\n'
                 % (LABELS[name], name))
    parts.append(src.strip())
    parts.append('\n')

text = '\n'.join(parts)
open('app.css', 'w', encoding='utf-8', newline='\n').write(text)

print('源文件合计字节: %d' % total)
print('app.css 字节  : %d' % len(text))
print('花括号配平    : %d == %d %s' % (text.count('{'), text.count('}'),
      'OK' if text.count('{') == text.count('}') else 'FAIL'))
print('.toast 保留   : %s' % ('.toast{' in text.replace(' ', '')))
print('font-family   : %d 处' % text.count('font-family'))
print('overflow:auto : %d 处' % text.count('overflow:auto'))