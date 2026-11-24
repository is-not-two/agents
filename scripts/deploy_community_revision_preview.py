"""Preview-only author revision/re-review deployment."""
import subprocess
from pathlib import Path

local=Path("src/rag_tech_retriever/api/routes/community.py").read_text(encoding="utf-8")
model=local[local.index("class Revision("):local.index("def digest(")]
mine=local[local.index('    @router.get("/mine")'):local.index('    @router.post("/withdraw")')]
review=local[local.index('    @router.post("/reviews")'):local.index('    @router.post("/ask")')]
script=r"""
from pathlib import Path
import os,tempfile,subprocess,time,ssl,urllib.request,json
root=Path("/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever")
route=root/"api/routes/community.py";main=root/"api/main.py";old={p:p.read_bytes() for p in (route,main)}
s=old[route].decode();m=old[main].decode();assert "class Revision(" not in s
a=s.index("class Review(");z=s.index("def digest(",a);s=s[:a]+model+s[z:]
a=s.index('    @router.get("/mine")');z=s.index('    @router.post("/withdraw")',a);s=s[:a]+mine+s[z:]
a=s.index('    @router.post("/reviews")');z=s.index('    @router.post("/ask")',a);s=s[:a]+review+s[z:]
a='("GET", "/api/community/session"),';assert m.count(a)==1
m=m.replace(a,a+' ("GET", "/api/community/draft"), ("POST", "/api/community/revise"),')
for name,text in ((route,s),(main,m)):compile(text,str(name),"exec")
def put(p,b):
 st=p.stat()
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(b);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,p)
try:
 put(route,s.encode());put(main,m.encode());subprocess.run(["systemctl","restart","shilie-preview"],check=True)
 ctx=ssl.create_default_context(cafile="/var/lib/shilie-preview/app/credentials/server.crt");ctx.check_hostname=False
 for i in range(30):
  try:
   with urllib.request.urlopen("https://127.0.0.1:8771/api/community/topics",context=ctx,timeout=3) as r:assert isinstance(json.load(r)["items"],list)
   print("PASS revision routes installed on 8771; feed available",flush=True);break
  except Exception:
   if i==29:raise
   time.sleep(1)
except BaseException:
 for p,b in old.items():put(p,b)
 subprocess.run(["systemctl","restart","shilie-preview"],check=True)
 raise
"""
ssh=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"]
subprocess.run(ssh,input=("model="+repr(model)+chr(10)+"mine="+repr(mine)+chr(10)+"review="+repr(review)+chr(10)+script).encode(),check=True)
