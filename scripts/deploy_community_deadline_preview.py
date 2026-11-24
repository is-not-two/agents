"""Publish bounded community model waits; leave global provider transport alone."""
import subprocess
from pathlib import Path

source=Path("src/rag_tech_retriever/platform/community_answers.py").read_bytes()
tests=Path("tests/test_community_answers.py").read_text(encoding="utf-8-sig")
script=r'''
from pathlib import Path
import os,subprocess,tempfile,ssl,urllib.request,time
p=Path("/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever/platform/community_answers.py")
old=p.read_bytes();assert b"completed.get(timeout=" not in old
compile(source,str(p),"exec")
def put(b):
 st=p.stat()
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(b);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,p)
restarted=False
try:
 put(source)
 with tempfile.TemporaryDirectory(prefix="community-deadline-") as folder:
  test=Path(folder)/"test_deadline.py";test.write_text(tests,encoding="utf-8")
  subprocess.run(["/var/lib/shilie-preview/app/.venv312/bin/python",str(test)],check=True)
 subprocess.run(["systemctl","restart","shilie-preview"],check=True);restarted=True
 ctx=ssl.create_default_context(cafile="/var/lib/shilie-preview/app/credentials/server.crt");ctx.check_hostname=False
 for i in range(30):
  try:
   with urllib.request.urlopen("https://127.0.0.1:8771/api/community/topics",context=ctx,timeout=3) as r:assert r.status==200
   print("PASS bounded community AI wait published; 8 contracts pass; feed 200");break
  except Exception:
   if i==29:raise
   time.sleep(1)
except BaseException:
 put(old)
 if restarted:subprocess.run(["systemctl","restart","shilie-preview"],check=True)
 raise
'''
ssh=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"]
subprocess.run(ssh,input=("source="+repr(source)+chr(10)+"tests="+repr(tests)+chr(10)+script).encode(),check=True)
