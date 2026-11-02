
P = 'E:/project/agents/rag-tech-doc-retriever/output/web/preview/horizontal-trail.html'
with open(P, encoding='utf-8') as _f:
    s = _f.read()

# 摘要行的分叉线向上飘：z-index:-1 落在 body 背景上，且 top:-32 超出容器。
# 改为：给 spine 加一个统一的"分叉柱"，从主干圆点向下延伸到分支起点。
old = '''.sum::before{content:"";position:absolute;left:-46px;top:-32px;width:60px;height:48px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;
  border-bottom-left-radius:26px;transform:skewX(-28deg);transform-origin:bottom left;z-index:-1}'''
s = s.replace(old, '')

old2 = '''.sum::before{content:"";position:absolute;left:-46px;top:-32px;width:60px;height:48px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;
  border-bottom-left-radius:26px;transform:skewX(-28deg);transform-origin:bottom left;z-index:-1}'''
s = s.replace(old2, '')

# 用伪元素统一画「圆点 → 分支」的斜线，挂在 spine 上而不是 branch/sum
hook = '.spine-dot{width:15px;height:15px;border-radius:50%;background:#fff;border:3px solid #d4a94a;'
addition = '''/* 从节点圆点斜向左下引出支线 */
.spine::after{content:"";position:absolute;left:50%;top:53px;width:64px;height:52px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;
  border-bottom-left-radius:28px;transform:skewX(-26deg);transform-origin:top left;
  z-index:0;pointer-events:none}
'''
s = s.replace('.spine-dot.todo{border-color:#c0cdd0;box-shadow:none}',
              '.spine-dot.todo{border-color:#c0cdd0;box-shadow:none}\n' + addition)

# branch / sum 不再各自画线，只做位移
s = s.replace('''.branch{position:relative;margin-top:-40px;margin-left:62px;width:250px}
.branch::before{content:"";position:absolute;left:-46px;top:-32px;width:60px;height:48px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;
  border-bottom-left-radius:26px;transform:skewX(-28deg);transform-origin:bottom left}''',
'''.branch{position:relative;margin-top:-40px;margin-left:62px;width:250px;z-index:1}''')

with open(P, 'w', encoding='utf-8', newline='\n') as _f:
    _f.write(s)

print('分叉线已统一挂到 spine')
print('spine::after 存在:', '.spine::after' in s)
print('sum::before 残留:', s.count('.sum::before'))
print('branch::before 残留:', s.count('.branch::before'))
