from pathlib import Path
import subprocess,base64
root=Path("src/rag_tech_retriever"); M=(root/"api/main.py").read_text(encoding="utf8")
block=M[M.index("    community_origin ="):M.index("    application.state.context = context")]
files={s:(root/s).read_bytes() for s in ["api/routes/community.py","platform/community_answers.py"]}
pre="block="+repr(block)+"\nfiles="+repr(files)+"\n"
script=r"""
from pathlib import Path
import os,tempfile,subprocess,time,urllib.request,ssl,json
from urllib.error import HTTPError
assert subprocess.check_output(["systemctl","show","shilie-preview","-p","User","--value"],text=True).strip()=="shilie_pvapp"
root=Path("/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever")
main=root/"api/main.py";s=main.read_text();a=s.index("    community_origin =");z=s.index("    application.state.context = context",a);assert '"/api/community/reviews"' in s[a:z] and '"/api/community/ask"' not in s[a:z]
files["api/main.py"]=(s[:a]+block+s[z:]).encode()
old={}
def put(p,b):
 st=(p if p.exists() else main).stat()
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(b);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,p)
def restart():subprocess.run(["systemctl","restart","shilie-preview"],check=True)
for name,data in files.items():compile(data,name,"exec")
try:
 for name,data in files.items():
  p=root/name;old[p]=p.read_bytes() if p.exists() else None;put(p,data)
 restart()
 for i in range(30):
  try:
   ctx=ssl._create_unverified_context();base="https://127.0.0.1:8771"
   def get(path):return urllib.request.urlopen(base+path,context=ctx,timeout=3).read()
   assert isinstance(json.loads(get("/api/community/topics"))["items"],list)
   req=urllib.request.Request(base+"/api/community/ask",b'{"question":"test","keywords":["test"]}',{"Content-Type":"application/json","Origin":"https://8.156.81.128:8771","Host":"8.156.81.128:8771"})
   try:urllib.request.urlopen(req,context=ctx)
   except HTTPError as e:assert e.code==401
   else:raise RuntimeError("guest must not invoke AI")
   print("PASS preview active, feed available, guest AI request denied");break
  except Exception:
   if i==29:raise
   time.sleep(1)
except BaseException:
 for p,b in old.items():
  if b is None:p.unlink(missing_ok=True)
  else:put(p,b)
 restart();raise
"""
subprocess.run(["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-o","IdentitiesOnly=yes","-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"],input=(pre+script).encode(),check=True)
