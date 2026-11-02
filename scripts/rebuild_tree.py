"""把预览页重写为单棵统一树：主线与支线在同一层级结构中，
仅靠颜色线区分。结构：根 -> 主线节点（金线）-> 子步骤（青灰线）。

替换预览文件的 CSS 与渲染函数部分。
"""
import re

P = 'E:/project/agents/rag-tech-doc-retriever/output/web/preview/horizontal-trail.html'
with open(P, encoding='utf-8') as _f:
    s = _f.read()

# ---------- 1) 树形 CSS ----------
old_css_start = s.find('.track{position:relative;')
old_css_end = s.find('.now{margin:')
assert old_css_start > 0 and old_css_end > old_css_start, '未定位到样式区间'

tree_css = '''.track{position:relative;padding:40px 44px 30px;width:max-content;min-width:max-content}

/* 统一树：一条主干向右延伸，主线节点与子步骤挂在其上 */
.tree{display:flex;align-items:flex-start;position:relative}
/* 主干：金线，贯穿全部主线 */
.trunk{position:absolute;left:0;right:24px;top:46px;height:4px;
  background:linear-gradient(90deg,#d4a94a,#f0dca4 45%,#d4a94a);
  box-shadow:0 0 9px #d4a94a5c;z-index:0}

/* 主线节点 */
.spine{position:relative;display:inline-flex;flex-direction:column;align-items:center;
  vertical-align:top;margin-right:34px;z-index:1}
.spine-dot{width:15px;height:15px;border-radius:50%;background:#fff;border:3px solid #d4a94a;
  margin:46px 0 12px;box-shadow:0 0 8px #d4a94a80;position:relative;z-index:3}
.spine-dot.todo{border-color:#c0cdd0;box-shadow:none}
.spine-dot.done{border-color:#4a8f5e;background:#4a8f5e}

.cover{width:150px;border-radius:9px;border:1px solid #d5c391;overflow:hidden;cursor:pointer;
  background:linear-gradient(150deg,#4a7c8c,#2d5866);color:#fff;padding:11px 10px;
  display:flex;flex-direction:column;gap:3px;transition:.15s}
.cover:hover{transform:translateY(-2px);box-shadow:0 6px 16px #12334133}
.cover.done{border-color:#8fbf9c;background:linear-gradient(150deg,#5d9470,#3d6b52)}
.cover.todo{border-color:#c0cdd0;background:linear-gradient(150deg,#7c9298,#5a7078)}
.cover.current{box-shadow:0 0 0 3px #d4a94a55,0 6px 16px #12334133}
.cover-name{font-size:14px;font-weight:600;line-height:1.35}
.cover-count{font-size:11.5px;opacity:.92}

/* 主线下的子步骤：从金线分出的青灰线 */
.branch{position:relative;margin-top:12px;padding-left:34px;width:186px}
.branch::before{content:"";position:absolute;left:12px;top:-14px;width:18px;height:26px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;border-bottom-left-radius:9px}
.branch::after{content:"";position:absolute;left:30px;top:12px;width:14px;height:2px;background:#93b3bc}
.branch[hidden]{display:none}

.sum{display:flex;align-items:center;gap:7px;width:186px;margin-top:12px;padding:7px 10px;
  background:#fff;border:1px dashed #b6cdd2;border-radius:7px;font-size:12px;color:#6b828a;
  text-align:left;transition:.15s}
.sum:hover{border-style:solid;border-color:#93b3bc;background:#fcfefe}
.sum-count{font-weight:700;color:#2b6b73;font-variant-numeric:tabular-nums;flex:none}
.sum-marks{color:#4a8f5e;letter-spacing:1px;font-size:11px;flex:none}
.sum-next{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#5d7680}
.sum-act{flex:none;color:#2b6b73;font-size:11.5px}

/* 支线步骤卡 */
.bitem{position:relative;display:flex;align-items:flex-start;gap:9px;padding:7px 9px 7px 11px;
  margin-bottom:6px;background:#fff;border:1px solid var(--line);border-radius:7px;width:186px}
.bitem:hover{border-color:#93b3bc;box-shadow:0 2px 8px #17384a12}
.bitem.on{background:#f7faf8}
.bitem:hover .btools{opacity:1}
.bitem:focus-within .btools{opacity:1}
.btools{display:flex;gap:3px;opacity:0;transition:opacity .15s;flex:none;margin-left:auto}
.btool{width:24px;height:24px;border-radius:5px;color:#8aa0a6;font-size:12px;display:grid;
  place-items:center;border:1px solid transparent;background:transparent;line-height:1}
.btool:hover{background:#eef4f4;color:#2b6b73;border-color:var(--line)}
.btool.del:hover{background:#fbeeea;color:#a4595a;border-color:#e8c4c4}

.tick{width:17px;height:17px;border-radius:50%;border:1.5px solid #b7cdd1;flex:none;margin-top:4px;
  display:grid;place-items:center;color:#fff;font-size:9px;font-weight:700}
.tick.on{background:#4a8f5e;border-color:#4a8f5e}
.tick:hover{border-color:var(--accent)}
.bbody{flex:1;min-width:0}
.badge{display:inline-flex;align-items:center;gap:5px;font-size:11px;padding:2px 7px;
  border-radius:3px;line-height:1.5;vertical-align:middle;margin-right:6px}
.badge::before{content:"";width:11px;height:11px;flex:none;border-radius:2px}
.badge.go{background:#d9ece6;color:#256553}
.badge.go::before{background:#3d8f7a}
.badge.doing{background:#d9ece6;color:#256553}
.badge.doing::before{background:#3d8f7a}
.badge.done{background:#e6ece8;color:#5b7361}
.badge.done::before{background:#fff;border:1.5px solid #6f8a78;
  box-shadow:inset 0 0 0 1.5px #6f8a78;border-radius:1px}
.bname{font-size:12.5px;line-height:1.45;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bmeta{font-size:10.5px;color:#8aa0a6;margin-top:3px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.pri{font-size:10.5px;font-weight:700;padding:1.5px 7px;border-radius:4px;letter-spacing:.3px}
.pri.p0{background:#b8544a;color:#fff}
.pri.p1{background:#d98a2b;color:#fff}
.pri.p2{background:#2b7884;color:#fff}
.pri.p3{background:#dfeaec;color:#5f7d84}
.pri.p4{background:#eef3f4;color:#8aa0a6}

/* 主线工具按钮 */
.spine-tools{display:flex;gap:6px;margin-top:10px;align-items:center;justify-content:center}
.tool{width:34px;height:34px;border-radius:8px;color:#5f7d84;font-size:17px;display:grid;
  place-items:center;border:1px solid var(--line);background:#fff;transition:.15s;line-height:1}
.tool:hover{background:#2b7884;color:#fff;border-color:#2b7884;transform:translateY(-1px)}
.tool.add{color:#2b7884;font-weight:700}
.tool.del:hover{background:#b8544a;color:#fff;border-color:#b8544a}

/* 末尾续接 */
.append{position:relative;display:inline-flex;flex-direction:column;align-items:center;
  justify-content:flex-start;gap:8px;width:120px;padding-top:52px;vertical-align:top;
  color:#8aa0a6;font-size:12px;cursor:pointer;margin-right:20px;z-index:1}
.append .plus{width:34px;height:34px;border-radius:50%;border:2px dashed #b6cdd2;
  display:grid;place-items:center;font-size:17px;color:#7fa3ac;background:#fbfdfd;transition:.15s}
.append:hover .plus{border-color:var(--accent);color:var(--accent);background:#eef6f6;transform:scale(1.08)}
.append:hover{color:#2b6b73}
.append .cap{margin:0;font-size:11.5px}

'''
s = s[:old_css_start] + tree_css + s[old_css_end:]

# ---------- 2) 渲染结构：主干 + 节点 ----------
s = s.replace(
    '<div class="track" id="track"><div class="axis"></div></div>',
    '<div class="track" id="track"><div class="tree" id="tree"><div class="trunk"></div></div></div>')

# spine：节点圆点 + 配图 + 工具 + 支线
s = re.sub(
    r'  return `<div class="spine\$\{focusId===d\.id.*?\n  </div>`;\n\}',
    '''  const cls=d.done===0?'todo':d.done===d.kids.length&&d.kids.length?'done':'doing';
  return `<div class="spine${focusId===d.id?' current':''}" data-sp="${d.id}">
    <span class="spine-dot ${cls}"></span>
    <div class="cover ${cls}"><span class="cover-name">${d.t}</span><span class="cover-count">${d.done}/${d.kids.length}</span></div>
    <div class="spine-tools">
      <button class="tool add" data-add="${d.id}" title="添加下一步" aria-label="在 ${d.t} 下添加">＋</button>
      <button class="tool" data-edit="${d.id}" title="编辑" aria-label="编辑 ${d.t}">✎</button>
      <button class="tool del" data-del="${d.id}" title="删除" aria-label="删除 ${d.t}">×</button>
    </div>
    ${open[d.id]?`<div class="branch" data-branch="${d.id}">
      ${d.kids.map((k,i)=>bitem(k,i===d.kids.length-1)).join('')}
    </div>`:summary(d)}
  </div>`;
}''', s, flags=re.DOTALL)

# render：写入 tree 容器并追加续接位
s = s.replace("""  tr.innerHTML='<div class="axis"></div>'
    +MAIN.map(spine).join('')""",
"""  tr.innerHTML='<div class="trunk"></div>'
    +MAIN.map(spine).join('')""")

with open(P, 'w', encoding='utf-8', newline='\n') as _f:
    _f.write(s)
print('已重写为统一树形结构')
print('trunk 存在:', 'class="trunk"' in s)
print('spine-dot 存在:', 'spine-dot' in s)
print('axis 残留:', s.count('class="axis"'), s.count('.axis{'))
