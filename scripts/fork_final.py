
P = 'E:/project/agents/rag-tech-doc-retriever/output/web/preview/horizontal-trail.html'
with open(P, encoding='utf-8') as _f:
    s = _f.read()

# 实测（spine 局部坐标）：
#   圆点   x=113..128  y=18..33   中心 (120, 25)
#   配图   x=66..216   y=73..137
#   工具   x=90..192   y=147..177
#   支线卡 x=31..281   y=171
# 目标：分叉线从圆点底部(120,33)垂直下探到 y=118（配图下方、工具上方），
#       再向左拐到支线左缘 x=31，拐角落在 (31,171) 上方。
# 即竖段 top=33 高 85，横段在 y≈118 处向左延伸 89px 到 x=31。
old = '''/* 从节点圆点斜向左下引出支线：起点在圆点下方，终点接支线卡片左上 */
.spine::after{content:"";position:absolute;left:119px;top:18px;width:92px;height:108px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;
  border-bottom-left-radius:44px;z-index:0;pointer-events:none}'''

new = '''/* 分叉线：自圆点垂直下探，再左拐至支线卡片，避免斜线穿过配图 */
.spine::after{content:"";position:absolute;left:119px;top:34px;width:89px;height:137px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;
  border-bottom-left-radius:20px;z-index:0;pointer-events:none}'''

s = s.replace(old, new)

# 支线卡紧贴拐角：branch y 从 171 保持，拐角底部应在 171 附近
s = s.replace('.branch{position:relative;margin-top:-6px;margin-left:31px;width:250px;z-index:1}',
              '.branch{position:relative;margin-top:-6px;margin-left:31px;width:250px;z-index:1}')
# 摘要行与支线卡对齐
s = s.replace('margin-top:10px;margin-left:31px;padding:7px 10px;',
              'margin-top:-6px;margin-left:31px;padding:7px 10px;')

with open(P, 'w', encoding='utf-8', newline='\n') as _f:
    _f.write(s)
print('分叉线改为「垂直下探 + 左拐」，不再穿过配图')
print('新坐标:', 'left:119px;top:34px;width:89px;height:137px' in s)
