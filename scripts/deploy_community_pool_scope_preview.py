"""Preview-only two-site connection-scope repair."""
import subprocess
from pathlib import Path

tests=Path("tests/test_community_pool_scope.py").read_text(encoding="utf-8-sig")
script=r"""
from pathlib import Path
import os,subprocess,tempfile,time,ssl,urllib.request
p=Path("/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever/api/routes/community.py")
old=p.read_bytes();s=old.decode()
for header in ('    def mine(request: Request) -> dict:','    def logout(request: Request) -> Response:'):
 start=s.index(header);end=s.index('    @router.',start)
 block=s[start:end]
 assert block.count('(session(request),)')==1 and 'key=session(request)' not in block
 block=block.replace('        with transaction() as cur:','        key=session(request)'+chr(10)+'        with transaction() as cur:',1)
 block=block.replace('(session(request),)','(key,)')
 s=s[:start]+block+s[end:]
compile(s,str(p),"exec")
def put(data):
 st=p.stat()
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(data);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,p)
restarted=False
try:
 put(s.encode())
 with tempfile.TemporaryDirectory(prefix="community-pool-scope-") as folder:
  test=Path(folder)/"test_scope.py";test.write_text(tests,encoding="utf-8")
  subprocess.run(["/var/lib/shilie-preview/app/.venv312/bin/python",str(test)],check=True)
 subprocess.run(["systemctl","restart","shilie-preview"],check=True);restarted=True
 ctx=ssl.create_default_context(cafile="/var/lib/shilie-preview/app/credentials/server.crt");ctx.check_hostname=False
 for i in range(30):
  try:
   with urllib.request.urlopen("https://127.0.0.1:8771/api/community/topics",context=ctx,timeout=3) as r:assert r.status==200
   print("PASS scope repair deployed to 8771; feed 200");break
  except Exception:
   if i==29:raise
   time.sleep(1)
except BaseException:
 put(old)
 if restarted:subprocess.run(["systemctl","restart","shilie-preview"],check=True)
 raise
"""
ssh=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"]
subprocess.run(ssh,input=("tests="+repr(tests)+chr(10)+script).encode(),check=True)
