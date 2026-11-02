
P = 'E:/project/agents/rag-tech-doc-retriever/output/web/preview/horizontal-trail.html'
with open(P, encoding='utf-8') as _f:
    s = _f.read()

# 实测坐标（spine 局部）：
#   圆点底   y=33
#   配图顶   y=73    配图左 x=66
#   工具顶   y=147   工具左 x=90
#   支线卡顶 y=171   支线卡左 x=31
#
# 竖段必须走 x=31（配图左侧空白），从拐点 y=78 向下到 y=171，
# 但会穿过工具区（x=90~192，y=147~177）——x=31 在其左侧，不冲突。
# 上一版竖段 top:77 height:94 → 终 y=171，正确。
# 但视觉上竖段太长。改为直接连到支线卡，长度 94 是必要的（78→171）。
# 真正的问题是竖段在配图左侧空白区悬空太久，视觉突兀。
#
# 改进：让斜段更长、竖段更短——斜段从圆点(120,33)走到 (31,120)，
# 竖段仅 120→171 共 51px，视觉上更紧凑。

s = s.replace(
 '.spine::after{content:"";position:absolute;left:34px;top:32px;width:86px;height:46px;',
 '.spine::after{content:"";position:absolute;left:33px;top:32px;width:87px;height:88px;')
s = s.replace(
 '.spine::before{content:"";position:absolute;left:33px;top:77px;width:2px;height:94px;',
 '.spine::before{content:"";position:absolute;left:32px;top:119px;width:2px;height:52px;')

with open(P, 'w', encoding='utf-8', newline='\n') as _f:
    _f.write(s)
print('折线已收紧：斜段更长，竖段仅 52px')
print('斜段:', 'left:33px;top:32px;width:87px;height:88px' in s)
print('竖段:', 'left:32px;top:119px;width:2px;height:52px' in s)
