"""Preview-only bounded model output budget, without changing model credentials."""
import subprocess
from pathlib import Path

source=Path("src/rag_tech_retriever/platform/community_answers.py").read_bytes()
tests=Path("tests/test_community_answers.py").read_text(encoding="utf-8-sig")
script=r'''
from pathlib import Path
import os,tempfile,subprocess,time,ssl,urllib.request
root=Path("/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever")
module=root/"platform/community_answers.py";main=root/"api/main.py"
old={p:p.read_bytes() for p in (module,main)}
assert b"completed.get(timeout=" in old[module] and b"max_output_tokens" not in old[module]
text=old[main].decode()
a='int(config.env("COMMUNITY_AI_TIMEOUT","20")))';assert text.count(a)==1
text=text.replace(a,'int(config.env("COMMUNITY_AI_TIMEOUT","20")),int(config.env("COMMUNITY_AI_MAX_OUTPUT_TOKENS","512")))')
compile(text,str(main),"exec");compile(source,str(module),"exec")
def put(p,data):
 st=p.stat()
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(data);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,p)
restarted=False
try:
 put(module,source);put(main,text.encode())
 with tempfile.TemporaryDirectory(prefix="community-budget-") as folder:
  test=Path(folder)/"test_budget.py";test.write_text(tests,encoding="utf-8")
  subprocess.run(["/var/lib/shilie-preview/app/.venv312/bin/python",str(test)],check=True)
 subprocess.run(["systemctl","restart","shilie-preview"],check=True);restarted=True
 ctx=ssl.create_default_context(cafile="/var/lib/shilie-preview/app/credentials/server.crt");ctx.check_hostname=False
 for i in range(30):
  try:
   with urllib.request.urlopen("https://127.0.0.1:8771/api/community/topics",context=ctx,timeout=3) as r:assert r.status==200
   print("PASS community budget 512 configurable, 11 contracts, preview feed 200");break
  except Exception:
   if i==29:raise
   time.sleep(1)
except BaseException:
 for p,data in old.items():put(p,data)
 if restarted:subprocess.run(["systemctl","restart","shilie-preview"],check=True)
 raise
'''
ssh=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"]
subprocess.run(ssh,input=("source="+repr(source)+chr(10)+"tests="+repr(tests)+chr(10)+script).encode(),check=True)
