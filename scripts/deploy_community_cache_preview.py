"""Preview-only epoch-aware anonymous response cache deployment."""
import subprocess
from pathlib import Path

source=Path("src/rag_tech_retriever/platform/community_public_cache.py").read_bytes()
tests=Path("tests/test_community_public_cache.py").read_text(encoding="utf-8-sig")
local=Path("src/rag_tech_retriever/api/routes/community.py").read_text(encoding="utf-8")
helper=local[local.index("    def public_response("):local.index('    @router.get("/topics"')]
topic_start=local.index('    @router.get("/topics"')
tail=local[local.index("            def load():",topic_start):local.index("    return router",topic_start)]
script=r'''
from pathlib import Path
import os,tempfile,subprocess,time,ssl,urllib.request,json
root=Path("/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever")
module=root/"platform/community_public_cache.py";route=root/"api/routes/community.py";main=root/"api/main.py"
old={p:(p.read_bytes() if p.exists() else None) for p in (module,route,main)}
s=old[route].decode();m=old[main].decode();assert "public_cache" not in s
a='owner_authorized: Callable | None = None) -> APIRouter:';assert s.count(a)==1
s=s.replace(a,'owner_authorized: Callable | None = None, public_cache=None) -> APIRouter:')
a=s.index('    @router.get("/search")');z=s.index('    @router.get("/topics")',a);s=s[:a]+helper+s[z:]
s=s.replace('    @router.get("/topics")','    @router.get("/topics",response_model=None)')
s=s.replace('def topics(before: UUID | None = None,','def topics(request: Request,before: UUID | None = None,')
s=s.replace('expected_version: int | None = Query(default=None,ge=1)) -> dict:','expected_version: int | None = Query(default=None,ge=1)) -> Response | dict:')
a=s.index('            sql = "SELECT id,title,score,published_at FROM community.public_topics "')
z=s.index('    return router',a);s=s[:a]+tail+s[z:]
a='        from rag_tech_retriever.platform.community_answers import CommunityAnswers';assert m.count(a)==1
m=m.replace(a,a+chr(10)+'        from rag_tech_retriever.platform.community_public_cache import PublicResponseCache')
a='            owner_authorized=lambda request: auth.enabled and not auth.is_mcp_token(request) and auth.authenticated(request),';assert m.count(a)==1
m=m.replace(a,a+chr(10)+'            public_cache=PublicResponseCache(int(config.env("COMMUNITY_PUBLIC_CACHE_ENTRIES","64")),int(config.env("COMMUNITY_PUBLIC_CACHE_BYTES","2097152"))) if int(config.env("COMMUNITY_PUBLIC_CACHE_ENTRIES","64")) else None,')
for name,text in ((route,s),(main,m)):compile(text,str(name),"exec")
compile(source,str(module),"exec")
def put(p,b):
 st=(p if p.exists() else main).stat()
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(b);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,p)
restarted=False
try:
 put(module,source);put(route,s.encode());put(main,m.encode())
 with tempfile.TemporaryDirectory(prefix="community-cache-contract-") as folder:
  test=Path(folder)/"test_cache.py";test.write_text(tests,encoding="utf-8")
  subprocess.run(["/var/lib/shilie-preview/app/.venv312/bin/python",str(test)],check=True)
 subprocess.run(["systemctl","restart","shilie-preview"],check=True);restarted=True
 ctx=ssl.create_default_context(cafile="/var/lib/shilie-preview/app/credentials/server.crt");ctx.check_hostname=False
 for i in range(30):
  try:
   with urllib.request.urlopen("https://127.0.0.1:8771/api/community/topics",context=ctx,timeout=3) as r:assert isinstance(json.load(r)["items"],list)
   print("PASS epoch-aware cache installed; four cache contracts; public feed healthy");break
  except Exception:
   if i==29:raise
   time.sleep(1)
except BaseException:
 for p,b in old.items():
  if b is None:p.unlink(missing_ok=True)
  else:put(p,b)
 if restarted:subprocess.run(["systemctl","restart","shilie-preview"],check=True)
 raise
'''
ssh=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"]
prefix="source="+repr(source)+chr(10)+"tests="+repr(tests)+chr(10)+"helper="+repr(helper)+chr(10)+"tail="+repr(tail)+chr(10)
subprocess.run(ssh,input=(prefix+script).encode(),check=True)
