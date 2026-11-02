
P = 'E:/project/agents/rag-tech-doc-retriever/output/web/preview/horizontal-trail.html'
with open(P, encoding='utf-8') as _f:
    s = _f.read()
before = s

old_branch = '''.branch{position:relative;margin-top:12px;padding-left:34px;width:250px}
.branch::before{content:"";position:absolute;left:12px;top:-14px;width:18px;height:26px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;border-bottom-left-radius:9px}
.branch::after{content:"";position:absolute;left:30px;top:12px;width:14px;height:2px;background:#93b3bc}'''

new_branch = '''/* 支线：斜向分叉，不在主干正下方 */
.branch{position:relative;margin-top:-40px;margin-left:62px;width:250px}
.branch::before{content:"";position:absolute;left:-46px;top:-32px;width:60px;height:48px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;
  border-bottom-left-radius:26px;transform:skewX(-28deg);transform-origin:bottom left}'''

if old_branch in s:
    s = s.replace(old_branch, new_branch)
else:
    print('警告：branch 块未匹配')

old_sum = '.sum{display:flex;align-items:center;gap:7px;width:250px;margin-top:12px;padding:7px 10px;'
new_sum = '.sum{display:flex;align-items:center;gap:7px;width:250px;margin-top:-40px;margin-left:62px;padding:7px 10px;'
s = s.replace(old_sum, new_sum)

# 摘要行的分叉线
hook = '.sum:hover{border-style:solid;border-color:#93b3bc;background:#fcfefe}'
fork = hook + '''
.sum::before{content:"";position:absolute;left:-46px;top:-32px;width:60px;height:48px;
  border-left:2px solid #93b3bc;border-bottom:2px solid #93b3bc;
  border-bottom-left-radius:26px;transform:skewX(-28deg);transform-origin:bottom left;z-index:-1}'''
s = s.replace(hook, fork)

# 间距调整
s = s.replace('vertical-align:top;margin-right:56px;z-index:1}',
              'vertical-align:top;margin-right:64px;z-index:1}')
s = s.replace('vertical-align:top;margin-right:40px;z-index:1}',
              'vertical-align:top;margin-right:64px;z-index:1}')
s = s.replace('.track{position:relative;padding:6px 44px 30px;',
              '.track{position:relative;padding:6px 70px 34px;')
s = s.replace('.trunk{position:absolute;left:0;right:24px;',
              '.trunk{position:absolute;left:24px;right:24px;')

with open(P, 'w', encoding='utf-8', newline='\n') as _f:
    _f.write(s)

print('变更:', 'YES' if s != before else 'NO')
print('branch 斜向 margin-left:', 'margin-left:62px' in s)
print('skewX 出现:', s.count('skewX(-28deg)'))
print('主干 left:24px:', 'left:24px;right:24px' in s)
