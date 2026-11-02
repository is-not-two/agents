
P = 'E:/project/agents/rag-tech-doc-retriever/output/web/preview/horizontal-trail.html'
with open(P, encoding='utf-8') as _f:
    s = _f.read()

# 问题：配图与工具按钮都在 spine 竖直排列，支线用负 margin 上移后
# 与工具按钮重叠。改为把工具按钮移到配图右侧，不占竖直通道。
old = '''.spine-tools{display:flex;gap:6px;margin-top:10px;position:relative;z-index:2}'''
new = '''/* 工具按钮移到配图右侧，让出竖直通道给支线分叉 */
.spine-tools{display:flex;gap:5px;margin-top:8px;position:relative;z-index:2;
  justify-content:center;flex-wrap:wrap;max-width:170px}'''
s = s.replace(old, new)

# 工具按钮缩小，避免与支线争空间
s = s.replace('.tool{width:34px;height:34px;border-radius:8px;color:#5f7d84;font-size:17px;',
              '.tool{width:30px;height:30px;border-radius:7px;color:#5f7d84;font-size:15px;')

# 支线再下移一点，确保与工具之间留出间距
s = s.replace('.branch{position:relative;margin-top:-28px;margin-left:31px;width:250px;z-index:1}',
              '.branch{position:relative;margin-top:-6px;margin-left:31px;width:250px;z-index:1}')
s = s.replace('.sum{display:flex;align-items:center;gap:7px;width:250px;margin-top:-28px;margin-left:31px;padding:7px 10px;',
              '.sum{display:flex;align-items:center;gap:7px;width:250px;margin-top:10px;margin-left:31px;padding:7px 10px;')

# 分叉线终点下移，对齐新的支线起点
s = s.replace('.spine::after{content:"";position:absolute;left:119px;top:20px;width:98px;height:88px;',
              '.spine::after{content:"";position:absolute;left:119px;top:18px;width:92px;height:108px;')

with open(P, 'w', encoding='utf-8', newline='\n') as _f:
    _f.write(s)
print('工具按钮已让位，支线间距已调整')
