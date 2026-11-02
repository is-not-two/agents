
P = 'E:/project/agents/rag-tech-doc-retriever/output/web/preview/horizontal-trail.html'
with open(P, encoding='utf-8') as _f:
    s = _f.read()

# 问题：分叉线竖段在 x=119，而配图占 x=66~216，竖线从圆点(120)直下必然穿过配图。
# 正确做法：让主干分叉发生在配图「上方」——即圆点处立即向左拐，
# 竖段放在配图左侧之外（x=31 附近），再向下接到支线。
#
# 实测：配图 left=66，分支卡 left=31。
# 方案：分叉线从圆点底部(120,33)向左下走到 (31,120)（配图左侧空白区），
#       再垂直下探到 (31,171) 接支线卡左上角。
# 用两个伪元素实现折线。
old = '''/* 分叉线：自圆点垂直下探，再左拐至支线卡片，避免斜线穿过配图 */
.spine::after{content:"";position:absolute;left:119px;top:34px;width:89px;height:137px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;
  border-bottom-left-radius:20px;z-index:0;pointer-events:none}'''

new = '''/* 分叉线：自圆点向左下引出，绕开配图左侧空白区，再垂直下探接支线。
   ::after 画斜段（圆点 → 拐点），::before 画竖段（拐点 → 支线卡）。 */
.spine::after{content:"";position:absolute;left:34px;top:32px;width:86px;height:46px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;
  border-bottom-left-radius:24px;z-index:0;pointer-events:none}
.spine::before{content:"";position:absolute;left:33px;top:77px;width:2px;height:94px;
  background:#93b3bc;z-index:0;pointer-events:none}'''

s = s.replace(old, new)
with open(P, 'w', encoding='utf-8', newline='\n') as _f:
    _f.write(s)
print('分叉线改为绕开配图的两段折线')
print('::after 斜段:', 'left:34px;top:32px;width:86px;height:46px' in s)
print('::before 竖段:', 'left:33px;top:77px;width:2px;height:94px' in s)
