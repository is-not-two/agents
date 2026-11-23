"""Preview-only bounded pool retention deployment and preflight."""
import subprocess
from pathlib import Path

tests=Path("tests/test_record_store_pool.py").read_text(encoding="utf-8")
script=r'''
import os,subprocess,tempfile,time,ssl,urllib.request,json
from pathlib import Path
pid=subprocess.check_output(["systemctl","show","shilie-preview","-p","MainPID","--value"],text=True).strip()
env=dict(v.split("=",1) for v in Path("/proc",pid,"environ").read_bytes().decode().split(chr(0)) if "=" in v)
assert env["POSTGRES_DB"]=="shilie_preview_20261104" and env["POSTGRES_PORT"]=="55433"
base=Path("/var/lib/shilie-preview/app")
root=base/".venv312/lib/python3.12/site-packages/rag_tech_retriever"
store=root/"platform/record_store.py";main=root/"api/main.py";cfg=base/"config/web.yaml"
old={p:p.read_bytes() for p in (store,main,cfg)}
s=old[store].decode()
a="pool_size: int = 0, pool_wait_seconds: float = 5.0) -> None:"
assert s.count(a)==1
s=s.replace(a,"pool_size: int = 0, pool_wait_seconds: float = 5.0, pool_min_size: int = 1) -> None:")
a="self.pool_size = max(0, int(pool_size))";assert s.count(a)==1
s=s.replace(a,a+chr(10)+"        self.pool_min_size = min(self.pool_size, max(1, int(pool_min_size)))")
a="ThreadedConnectionPool(1, self.pool_size,";assert s.count(a)==1
s=s.replace(a,"ThreadedConnectionPool(self.pool_min_size, self.pool_size,")
m=old[main].decode();a='pool_wait_seconds=float(config.get("web.db_pool_wait_seconds", 5)),'
assert m.count(a)==1
m=m.replace(a,a+chr(10)+'        pool_min_size=int(config.get("web.db_pool_min_size", 1)),')
c=old[cfg].decode();assert "  db_pool_size: 8" in c and "db_pool_min_size:" not in c
c=c.replace("  db_pool_size: 8","  db_pool_size: 8"+chr(10)+"  db_pool_min_size: 8")
for name,text in ((store,s),(main,m)):compile(text,str(name),"exec")
def put(p,b):
 st=p.stat()
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(b);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,p)
restarted=False
try:
 for p,text in ((store,s),(main,m),(cfg,c)):put(p,text.encode())
 verification = """
from unittest.mock import patch
from rag_tech_retriever.platform.record_store import RecordStore,StorageError
from psycopg2 import pool as pg_pool
for maximum,minimum,expected in [(0,8,0),(8,0,1),(8,8,8),(8,99,8)]:
 assert RecordStore('qa_pool',pool_size=maximum,pool_min_size=minimum).pool_min_size==expected
assert RecordStore('qa_pool')._connection_pool() is None
marker=object()
with patch.object(pg_pool,'ThreadedConnectionPool',return_value=marker) as factory:
 store=RecordStore('qa_pool',pool_size=8,pool_min_size=8)
 assert store._connection_pool() is marker and store._connection_pool() is marker
 assert factory.call_count==1 and factory.call_args.args==(8,8)
with patch.object(pg_pool,'ThreadedConnectionPool',side_effect=__import__('psycopg2').OperationalError('offline')):
 assert RecordStore('qa_pool',pool_size=8,pool_min_size=8)._connection_pool() is None
class Empty:
 def getconn(self):raise pg_pool.PoolError('full')
store=RecordStore('qa_pool',pool_size=8,pool_wait_seconds=0)
with patch.object(store,'_connection_pool',return_value=Empty()):
 try:
  with store.transaction():raise AssertionError('must not execute')
 except StorageError:pass
print('PASS default off, min bounds, persistent idle allocation, create once, unavailable fallback, exhausted pool')
"""
 subprocess.run([str(base/".venv312/bin/python"),"-c",verification],env=env,check=True,cwd=str(base))
 subprocess.run(["systemctl","restart","shilie-preview"],check=True);restarted=True
 ctx=ssl.create_default_context(cafile=str(base/"credentials/server.crt"));ctx.check_hostname=False
 for i in range(30):
  try:
   with urllib.request.urlopen("https://127.0.0.1:8771/api/community/topics",context=ctx,timeout=3) as r:
    assert r.status==200 and isinstance(json.load(r)["items"],list)
   print("PASS pool tests, preview restarted, public feed available",flush=True);break
  except Exception:
   if i==29:raise
   time.sleep(1)
except BaseException:
 for p,b in old.items():put(p,b)
 if restarted:subprocess.run(["systemctl","restart","shilie-preview"],check=True)
 raise
'''
ssh=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"]
subprocess.run(ssh,input=("tests="+repr(tests)+chr(10)+script).encode(),check=True)
