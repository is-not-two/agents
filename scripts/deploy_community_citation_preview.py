"""Preview citation version check; keep public attachment gates unchanged."""
import subprocess
from pathlib import Path

script=r'''
from pathlib import Path
import os,tempfile,subprocess,ssl,urllib.request,time
p=Path("/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever/api/routes/community.py")
old=p.read_bytes();s=old.decode()
a="def topics(before: UUID | None = None, topic: UUID | None = None) -> dict:";assert s.count(a)==1
s=s.replace(a,"def topics(before: UUID | None = None, topic: UUID | None = None, expected_version: int | None = Query(default=None,ge=1)) -> dict:")
a='        """Stable descending feed; only published posts are available here."""';assert s.count(a)==1
s=s.replace(a,a+chr(10)+'        if expected_version is not None and topic is None:'+chr(10)+'            raise HTTPException(422,"引用版本需要同时指定帖子")')
a='                    raise HTTPException(404,"找不到已公开的帖子")';assert s.count(a)==1
s=s.replace(a,a+chr(10)+'                if expected_version is not None and row["version"]!=expected_version:'+chr(10)+'                    raise HTTPException(409,"这条引用对应的版本已变化，请重新检索，不要把新版当作原引用")')
compile(s,str(p),"exec")
def put(b):
 st=p.stat()
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(b);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,p)
try:
 put(s.encode());subprocess.run(["systemctl","restart","shilie-preview"],check=True)
 ctx=ssl.create_default_context(cafile="/var/lib/shilie-preview/app/credentials/server.crt");ctx.check_hostname=False
 for i in range(30):
  try:
   with urllib.request.urlopen("https://127.0.0.1:8771/api/community/topics",context=ctx,timeout=3) as r:assert r.status==200
   print("PASS citation version guard installed; public feed 200");break
  except Exception:
   if i==29:raise
   time.sleep(1)
except BaseException:
 put(old);subprocess.run(["systemctl","restart","shilie-preview"],check=True);raise
'''
ssh=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"]
subprocess.run(ssh,input=script.encode(),check=True)
