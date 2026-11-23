"""Preview-only owner bridge deployment. No public role assignment endpoint."""
from pathlib import Path
import subprocess
local=Path("src/rag_tech_retriever/api/routes/community.py").read_text(encoding="utf-8")
session_check=local[local.index("        key=digest(token)",local.index("    def session(")):local.index('    @router.get("/session")')]
handlers=local[local.index('    @router.get("/session")'):local.index('    @router.post("/session", status_code=201)')]
script=r"""
from pathlib import Path
import os,tempfile,subprocess,time,ssl,urllib.request,json
root=Path("/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever")
route=root/"api/routes/community.py";main=root/"api/main.py";old={p:p.read_bytes() for p in (route,main)}
s=old[route].decode();m=old[main].decode()
assert 'owner_authorized' not in s
a='session_seconds: int, answers=None) -> APIRouter:';assert s.count(a)==1
s=s.replace(a,'session_seconds: int, answers=None, owner_authorized: Callable | None = None) -> APIRouter:')
a='        return digest(token)';assert s.count(a)==1
s=s.replace(a,session_check.rstrip()+chr(10))
a='    @router.post("/session", status_code=201)';assert s.count(a)==1
s=s.replace(a,handlers+a)
a='("POST", "/api/community/session"), ("DELETE", "/api/community/session"),';assert m.count(a)==1
m=m.replace(a,a+' ("GET", "/api/community/session"),')
a='            session_seconds=int(config.env("COMMUNITY_SESSION_SECONDS", "28800")),'
assert m.count(a)==1
m=m.replace(a,a+chr(10)+'            owner_authorized=lambda request: auth.enabled and not auth.is_mcp_token(request) and auth.authenticated(request),')
allow=m[m.index("    community_endpoints ="):m.index("    if community_origin:",m.index("    community_endpoints ="))]
assert "workspace-session" not in allow
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
   print("PASS preview owner bridge installed; public allowlist does not include owner bridge",flush=True);break
  except Exception:
   if i==29:raise
   time.sleep(1)
except BaseException:
 for p,b in old.items():put(p,b)
 subprocess.run(["systemctl","restart","shilie-preview"],check=True)
 raise
"""
ssh=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"]
subprocess.run(ssh,input=("session_check="+repr(session_check)+chr(10)+"handlers="+repr(handlers)+chr(10)+script).encode(),check=True)
