
P = 'E:/project/agents/rag-tech-doc-retriever/output/web/preview/horizontal-trail.html'
with open(P, encoding='utf-8') as _f:
    s = _f.read()

# 实测坐标（视口 1400）：圆点中心 x=226 y=252（spine 原点 x=101），
# 配图 y=272~336，支线卡 x=132 y=340。
# 分叉线需从圆点(226,252)斜向左下到支线左上(132,340)。
# spine 内坐标：圆点中心约 (125, 16)，支线左上约 (31, 104)。
old = '''/* 从节点圆点斜向左下引出支线 */
.spine::after{content:"";position:absolute;left:50%;top:53px;width:64px;height:52px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;
  border-bottom-left-radius:28px;transform:skewX(-26deg);transform-origin:top left;
  z-index:0;pointer-events:none}'''

new = '''/* 从节点圆点斜向左下引出支线：起点在圆点下方，终点接支线卡片左上 */
.spine::after{content:"";position:absolute;left:119px;top:20px;width:98px;height:88px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;
  border-bottom-left-radius:44px;z-index:0;pointer-events:none}'''

s = s.replace(old, new)

# 支线容器上移贴近分叉线终点
s = s.replace('.branch{position:relative;margin-top:-40px;margin-left:62px;width:250px;z-index:1}',
              '.branch{position:relative;margin-top:-28px;margin-left:31px;width:250px;z-index:1}')
s = s.replace('.sum{display:flex;align-items:center;gap:7px;width:250px;margin-top:-40px;margin-left:62px;padding:7px 10px;',
              '.sum{display:flex;align-items:center;gap:7px;width:250px;margin-top:-28px;margin-left:31px;padding:7px 10px;')

# 工具按钮上移，让分叉线有通道
s = s.replace('.spine-tools{display:flex;gap:6px;margin-top:10px;',
              '.spine-tools{display:flex;gap:6px;margin-top:10px;position:relative;z-index:2;')

with open(P, 'w', encoding='utf-8', newline='\n') as _f:
    _f.write(s)

print('分叉线已按实测坐标定位')
print('spine::after 坐标:', 'left:119px;top:20px' in s)
print('branch margin-left:', 'margin-left:31px' in s)
