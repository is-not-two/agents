import re

P = 'E:/project/agents/rag-tech-doc-retriever/output/web/preview/horizontal-trail.html'
with open(P, encoding='utf-8') as _f:
    s = _f.read()
orig = s

# 1) 移除章节标签（用户要求）
s = s.replace('    <div class="chapter"><span class="${ch}">${d.t} . ${d.done}/${d.total}</span></div>\n', '')
s = s.replace('    <div class="chapter"><span class="${ch}">${d.t} · ${d.done}/${d.total}</span></div>\n', '')
s = re.sub(r'\.chapter\{[^}]*\}\n', '', s)
s = re.sub(r'\.chapter span\{[^}]*\}\n(\.chapter span::before\{[^}]*\}\n)?(\.chapter span\.done::before\{[^}]*\}\n)?(\.chapter span\.doing::before\{[^}]*\}\n)?', '', s)
s = s.replace('.spine.current .chapter span{box-shadow:0 0 0 2px #c9a96188}\n', '')

# 2) 主线金线：加粗、贯穿，每段向右延伸 40px 保持连续
s = s.replace('height:3px;\n  background:linear-gradient(90deg,#c9a961,#e6d4a6 60%,#c9a961);\n  box-shadow:0 0 6px #c9a9614d}',
              'height:4px;\n  background:linear-gradient(90deg,#d4a94a,#f0dca4 45%,#d4a94a);\n  box-shadow:0 0 8px #d4a94a5e}')
s = s.replace('top:-3px;width:9px;height:9px;\n  border-radius:50%;background:#fff;border:2px solid #c9a961;',
              'top:-4px;width:12px;height:12px;\n  border-radius:50%;background:#fff;border:3px solid #d4a94a;')
s = s.replace('box-shadow:0 0 6px #c9a96166}', 'box-shadow:0 0 8px #d4a94a80}')

# 3) 支线线条改为青灰色，与主线金线区分
s = s.replace('border-left:2px solid #b9cdd2;border-bottom:2px solid #b9cdd2;border-bottom-left-radius:9px}',
              'border-left:2px solid #9fbcc4;border-bottom:2px solid #9fbcc4;border-bottom-left-radius:9px}')
s = s.replace('.bitem::after{content:"";position:absolute;right:-20px;top:50%;width:20px;height:2px;background:#c9d8dc}',
              '.bitem::after{content:"";position:absolute;right:-20px;top:50%;width:20px;height:2px;background:#9fbcc4}')
s = s.replace('border-top:1.5px solid #c9d8dc;border-right:1.5px solid #c9d8dc;',
              'border-top:1.5px solid #9fbcc4;border-right:1.5px solid #9fbcc4;')
s = s.replace('width:2px;height:50px;background:#b8913fa8;', 'width:2px;height:46px;background:#d4a94a9e;')

# 4) 主线名与进度移进配图内
s = s.replace('<div class="cover ${ch}">${d.t}</div>',
              '<div class="cover ${ch}"><span class="cover-name">${d.t}</span><span class="cover-count">${d.done}/${d.kids.length}</span></div>')
s = s.replace('.cover.done{border-color:#8fbf9c;background:linear-gradient(135deg,#5d9470,#3d6b52)}',
              '.cover.done{border-color:#8fbf9c;background:linear-gradient(135deg,#5d9470,#3d6b52)}\n'
              '.cover{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px}\n'
              '.cover-name{font-size:14px;font-weight:600}\n'
              '.cover-count{font-size:11.5px;opacity:.92}')

with open(P, 'w', encoding='utf-8', newline='\n') as _f:
    _f.write(s)
print('已应用：章节标签移除、主线金线加粗、支线青灰、名称移入配图')
print('chapter 残留:', s.count('chapter{'), s.count('class="chapter"'))
print('cover-name 存在:', 'cover-name' in s)
print('主线色 #d4a94a 次数:', s.count('#d4a94a'))
print('支线色 #9fbcc4 次数:', s.count('#9fbcc4'))
