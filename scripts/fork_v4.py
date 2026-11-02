
P = 'E:/project/agents/rag-tech-doc-retriever/output/web/preview/horizontal-trail.html'
with open(P, encoding='utf-8') as _f:
    s = _f.read()

# 现状：横向段终点在 y=120，正好贴着配图底部（y=137）上方 17px，
# 视觉上像"从配图里伸出条尾巴"。要让横向段在配图上方就拐弯，
# 然后竖段贴着配图左侧下行，视觉更干净。
#
# 实测：配图 x=66..216, y=73..137；支线卡 x=31, y=171
# 改：斜段 top:32 高:52 → 拐点(33,84)，在配图顶部之上
#     竖段 top:84 高:87 → 到底(33,171) 接支线卡
s = s.replace(
 '.spine::after{content:"";position:absolute;left:33px;top:32px;width:87px;height:88px;',
 '.spine::after{content:"";position:absolute;left:33px;top:32px;width:87px;height:50px;')
s = s.replace(
 '.spine::before{content:"";position:absolute;left:32px;top:119px;width:2px;height:52px;',
 '.spine::before{content:"";position:absolute;left:32px;top:81px;width:2px;height:90px;')
# 圆角改小，避免大弧线
s = s.replace('border-bottom-left-radius:24px;z-index:0;pointer-events:none}',
              'border-bottom-left-radius:18px;z-index:0;pointer-events:none}')

with open(P, 'w', encoding='utf-8', newline='\n') as _f:
    _f.write(s)
print('拐点已上移到配图顶部之上')
print('斜段:', 'top:32px;width:87px;height:50px' in s)
print('竖段:', 'top:81px;width:2px;height:90px' in s)
