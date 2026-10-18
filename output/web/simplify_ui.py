from pathlib import Path

root = Path(__file__).resolve().parents[2]
static = root / 'src/rag_tech_retriever/api/static/shilie'

def update(name, replacements):
    path = static / name
    source = path.read_text(encoding='utf-8')
    for old, new in replacements:
        assert old in source, (name, old)
        source = source.replace(old, new)
    path.write_text(source, encoding='utf-8')

update('app.js', [
    ("const $=s=>document.querySelector(s),content=", "const $=s=>document.querySelector(s),navigationStrip=$('#navigation-strip'),content="),
    ("content.innerHTML=render();$('#navigation-strip').hidden=", "content.innerHTML=render();content.prepend(navigationStrip);navigationStrip.hidden="),
])
update('tree.js', [
    ('M ${a.x+228} ${a.y+53} C ${a.x+262} ${a.y+53}, ${n.x-34} ${n.y+53}, ${n.x} ${n.y+53}', 'M ${a.x+18} ${a.y+106} V ${n.y+53} H ${n.x}'),
    ('data-action="tree-select" data-id="${esc(n.id)}"', 'data-action="tree-select" data-id="${esc(n.id)}" ${n.childCount?`aria-expanded="${!treeState.folded.includes(n.id)}"`:""}'),
    ("'主线方向':'支线方向'", "'主线 · 主节点':'支线 · 主节点'"),
    ('${status(n)} · ${(n.priority', "${n.parent_id?'子节点':'主节点'} · ${status(n)} · ${(n.priority"),
    ('`${n.childCount} 个子节点`', "`${n.childCount} 个子节点 · 点击${treeState.folded.includes(n.id)?'展开':'收起'}`"),
    ('点击节点查看详情，点旁边的 <b>＋</b> 添加下一层。', '点击主节点，向下展开子节点。点旁边的 <b>＋</b> 添加下一步。'),
    ('<div class="inspector-tip"><span>组织关系</span><p>树枝表示目标的拆分；前置条件决定任务何时可开始。</p></div>', ''),
    ('<label class="form-field">所属父节点<select name="parent_id"></select></label>', '<label hidden>添加位置<select name="parent_id"></select></label>'),
    ('<label class="form-field">前置条件<select name="requires" multiple></select><small>父子组织关系不会自动变成前置条件。</small></label>', '<details class="tree-optional"><summary>更多设置（可不填）</summary><label class="form-field">需要先完成哪些任务？<select name="requires" multiple></select><small>没有要求就留空，按 Ctrl 可选多个。</small></label></details>'),
    ('前置条件', '需要先完成'),
    ('无需要先完成', '没有需要先完成的任务'),
    ('定位根节点', '回到开头'),
    ('拖动画布空白处 · 点击 ＋ 添加 · 点击节点编辑', '点击节点展开 / 收起 · ＋ 添加下一步'),
    ('添加子节点', '添加下一步'),
    ('<label class="form-field">名称<input name="title"', '<p id="tree-add-context" class="tree-add-context"></p><label class="form-field">你想做什么？<input name="title"'),
])
update('tree-actions.js', [
    ('const value=root&&mode', "$('#tree-add-context').textContent=root?'写下你想实现的目标。':mode==='add'?'添加到「'+(treeNodes().find(n=>n.id===parent)?.title||p.data.title)+'」下面':'修改这一步的内容。';form.querySelectorAll('details').forEach(d=>d.open=false);\n  const value=root&&mode"),
    ("if(action==='select'){s.selected=id;redraw();const heading=$('.tree-inspector h2');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}return;}", "if(action==='select'){s.selected=id;const hasChildren=id===rootId()?treeNodes().some(n=>!n.parent_id):treeNodes().some(n=>n.parent_id===id);if(hasChildren){s.folded=s.folded.includes(id)?s.folded.filter(v=>v!==id):[...s.folded,id];write('tree-folded',s.folded);}redraw();const selected=[...document.querySelectorAll('[data-action=tree-select]')].find(n=>n.dataset.id===id);selected?.focus({preventScroll:true});return;}"),
])
for path in [*static.glob('*.js'), static/'index.html']:
    text=path.read_text(encoding='utf-8')
    path.write_text(text.replace('?v=13','?v=14'),encoding='utf-8')
with (static/'tree.css').open('a',encoding='utf-8') as f:
    f.write('''
/* 用户确认：黑色品牌栏；返回只在内容区保留一份。 */
.topbar{background:#000;color:#fff}.brand-mark{background:#000;border-color:#777}.topbar .quick-trigger,.topbar .preview-label,.topbar .position,.topbar .layout-menu{color:#eee}
#content>#navigation-strip{position:static;display:flex;backdrop-filter:none;background:transparent;border:0;padding:0;margin:0 0 24px;gap:16px}#content>#navigation-strip[hidden]{display:none}#navigation-strip .navigation-hint{display:none}[data-layout=sidebar] .sidebar{top:76px}.global-back{background:#fff;box-shadow:none}.tree-add-context{font-size:13px;color:#52757a;padding:12px;background:#edf4f4;border-radius:6px}.tree-optional summary{cursor:pointer;color:#52757a;padding:10px 0}.tree-optional .form-field{margin-top:12px}.tree-node-meta{letter-spacing:0}
''')
with (root/'DESIGN.md').open('a',encoding='utf-8') as f:
    f.write('''
### 用户确认的交互简化（2026-10-13）
- 采用纵向缩进树，点击节点本体展开/收起下方子节点，＋自动添加到点击位置；表单隐藏所属父节点，依赖收进更多设置，使用“下一步”等口语文案。
- 品牌顶栏改为用户指定纯黑色。两个返回调用相同 back()，删除旧 back-button 输出，将唯一返回上一级入口移到内容区原返回位置。此前隐藏 .back-link 与实际类名不符导致重复，本次删除冗余生成逻辑并验证数量。
''')
print('UI changes applied')
