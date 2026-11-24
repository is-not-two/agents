"""Preview-only community excerpt fairness update, with baseline/candidate tests."""
import subprocess
from pathlib import Path

source=Path("src/rag_tech_retriever/platform/community_answers.py").read_bytes()
tests=Path("tests/test_community_answers.py").read_text(encoding="utf-8-sig")
script=r"""
from pathlib import Path
import subprocess,tempfile,os,time,ssl,urllib.request,json
base=Path("/var/lib/shilie-preview/app")
target=base/".venv312/lib/python3.12/site-packages/rag_tech_retriever/platform/community_answers.py"
python=str(base/".venv312/bin/python")
assert subprocess.check_output(["systemctl","show","shilie-preview","-p","User","--value"],text=True).strip()=="shilie_pvapp"
old=target.read_bytes();compile(source,str(target),"exec")
assert b"evidence[:40]" in old and b"zip_longest" not in old
def put(blob):
 st=target.stat()
 with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as f:f.write(blob);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,target)
restarted=False
try:
 with tempfile.TemporaryDirectory(prefix="community-evidence-") as d:
  test=Path(d)/"test_evidence.py";test.write_text(tests,encoding="utf-8")
  baseline=subprocess.run([python,str(test)],capture_output=True,text=True)
  assert baseline.returncode==1 and "FAILED (failures=2)" in baseline.stderr,baseline.stderr
  print("BASELINE: 6 tests, 2 expected fairness failures",flush=True)
  put(source)
  subprocess.run([python,str(test)],check=True)
 subprocess.run(["systemctl","restart","shilie-preview"],check=True);restarted=True
 ctx=ssl.create_default_context(cafile=str(base/"credentials/server.crt"));ctx.check_hostname=False
 for i in range(30):
  try:
   with urllib.request.urlopen("https://127.0.0.1:8771/api/community/topics",context=ctx,timeout=3) as r:
    assert r.status==200 and isinstance(json.load(r)["items"],list)
   print("MODIFIED: 6 tests pass; preview active; feed 200",flush=True);break
  except Exception:
   if i==29:raise
   time.sleep(1)
except BaseException:
 put(old)
 if restarted:subprocess.run(["systemctl","restart","shilie-preview"],check=True)
 raise
"""
ssh=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-o","IdentitiesOnly=yes",
     "-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"]
subprocess.run(ssh,input=("source="+repr(source)+chr(10)+"tests="+repr(tests)+chr(10)+script).encode(),check=True)
