"""Narrow preview-only pagination publication; do not replace the whole route module."""
import subprocess
from pathlib import Path

local=Path('src/rag_tech_retriever/api/routes/community.py').read_text(encoding='utf-8')
payload={
 'module':Path('src/rag_tech_retriever/platform/community_pagination.py').read_bytes(),
 'mine':local[local.index('    @router.get("/mine")'):local.index('    @router.get("/draft")')],
 'reviews':local[local.index('    @router.get("/reviews")'):local.index('    @router.post("/reviews")')],
 'tests':Path('tests/test_community_pagination.py').read_bytes(),
}
script=r'''
from pathlib import Path
import os,subprocess,tempfile,time,ssl,json,urllib.request,hashlib
root=Path('/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever')
module=root/'platform/community_pagination.py';route=root/'api/routes/community.py'
old={p:p.read_bytes() if p.exists() else None for p in (module,route)}
index=root/'api/static/vue/index.html';index_hash=hashlib.sha256(index.read_bytes()).hexdigest()
prod_pid=subprocess.check_output(['systemctl','show','shilie','-p','MainPID','--value'],text=True).strip()
text=old[route].decode();assert 'community_pagination' not in text
for start,end,key in [('    @router.get("/mine")','    @router.get("/draft")','mine'),('    @router.get("/reviews")','    @router.post("/reviews")','reviews')]:
 a=text.index(start);b=text.index(end,a);text=text[:a]+payload[key]+text[b:]
needle='from pydantic import BaseModel, Field';assert text.count(needle)==1
text=text.replace(needle,needle+'\nfrom rag_tech_retriever.platform.community_pagination import decode_cursor, page_result')
for p,b in ((module,payload['module']),(route,text.encode())):compile(b,str(p),'exec')
def put(p,b):
 st=(p if p.exists() else route).stat()
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(b);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,p)
restarted=False
try:
 put(module,payload['module']);put(route,text.encode())
 with tempfile.TemporaryDirectory(prefix='community-pagination-') as folder:
  f=Path(folder)/'test_pagination.py';f.write_bytes(payload['tests'])
  subprocess.run(['/var/lib/shilie-preview/app/.venv312/bin/python',str(f)],check=True)
 subprocess.run(['systemctl','restart','shilie-preview'],check=True);restarted=True
 ctx=ssl.create_default_context(cafile='/var/lib/shilie-preview/app/credentials/server.crt');ctx.check_hostname=False
 for i in range(30):
  try:
   with urllib.request.urlopen('https://127.0.0.1:8771/api/community/topics',context=ctx,timeout=4) as r:assert isinstance(json.load(r)['items'],list)
   break
  except Exception:
   if i==29:raise
   time.sleep(1)
 assert hashlib.sha256(index.read_bytes()).hexdigest()==index_hash
 assert subprocess.check_output(['systemctl','show','shilie','-p','MainPID','--value'],text=True).strip()==prod_pid
 print('PASS pagination installed; 3 cursor contracts; feed200; private index and production PID unchanged')
except BaseException:
 for p,b in old.items():
  if b is None:p.unlink(missing_ok=True)
  else:put(p,b)
 if restarted:subprocess.run(['systemctl','restart','shilie-preview'],check=True)
 raise
'''
ssh=['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes',
     '-i',str(Path.home()/'.ssh/selfstock_8_156_81_128_rsa'),'root@8.156.81.128','python3 -']
subprocess.run(ssh,input=('payload='+repr(payload)+'\n'+script).encode(),check=True)
