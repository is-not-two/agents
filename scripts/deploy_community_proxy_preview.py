"""Use existing nginx for preview TLS; preserve one worker and application limits."""
import subprocess
from pathlib import Path

payload = {name: Path(name).read_bytes() for name in (
    "config/shilie-preview-proxy.conf", "config/shilie-preview-proxy-runtime.conf",
    "src/rag_tech_retriever/common/middleware/compression.py",
    "src/rag_tech_retriever/platform/community_public_cache.py",
    "tests/test_community_public_cache.py", "tests/test_compression_negotiation.py",
)}
script = r'''
from pathlib import Path
import os,subprocess,tempfile,time,ssl,urllib.request,json,hashlib
root=Path('/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever')
nginx=Path('/etc/nginx/sites-enabled/shilie-preview-8771.conf')
unit=Path('/etc/systemd/system/shilie-preview.service.d/zzzzzzz-community-proxy.conf')
assert not nginx.exists() and not unit.exists(),'already installed: inspect instead of repeating'
effective=subprocess.check_output(['nginx','-T'],stderr=subprocess.STDOUT,text=True)
assert not any('listen' in line and '8771' in line for line in effective.splitlines())
prod_pid=subprocess.check_output(['systemctl','show','shilie','-p','MainPID','--value'],text=True).strip()
unit_before=subprocess.check_output(['systemctl','show','shilie-preview','-p','ExecStart','--value'],text=True)
assert '--port 8771' in unit_before and '--workers 1' in unit_before
index=root/'api/static/vue/index.html';index_hash=hashlib.sha256(index.read_bytes()).hexdigest()
ctx=ssl.create_default_context(cafile='/var/lib/shilie-preview/app/credentials/server.crt');ctx.check_hostname=False
def feed(url,context=None):
 with urllib.request.urlopen(url,context=context,timeout=5) as r:
  assert r.status==200 and isinstance(json.load(r)['items'],list)
feed('https://127.0.0.1:8771/api/community/topics',ctx)
files={root/'common/middleware/compression.py':payload['src/rag_tech_retriever/common/middleware/compression.py'],
       root/'platform/community_public_cache.py':payload['src/rag_tech_retriever/platform/community_public_cache.py']}
main=root/'api/main.py';text=main.read_text()
old_import='from starlette.middleware.gzip import GZipMiddleware'
assert text.count(old_import)==1 and text.count('application.add_middleware(GZipMiddleware,')==1
text=text.replace(old_import,'from rag_tech_retriever.common.middleware.compression import NegotiatedGZipMiddleware')
text=text.replace('application.add_middleware(GZipMiddleware,','application.add_middleware(NegotiatedGZipMiddleware,')
files[main]=text.encode()
old={p:p.read_bytes() if p.exists() else None for p in files}
for p,b in files.items():compile(b,str(p),'exec')
def put(p,b):
 st=(p if p.exists() else main).stat()
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(b);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,p)
reconfigured=False
try:
 for p,b in files.items():put(p,b)
 with tempfile.TemporaryDirectory(prefix='preview-compression-') as folder:
  for name in ('test_community_public_cache.py','test_compression_negotiation.py'):
   f=Path(folder)/name;f.write_bytes(payload['tests/'+name])
   subprocess.run(['/var/lib/shilie-preview/app/.venv312/bin/python',str(f)],check=True)
 nginx.write_bytes(payload['config/shilie-preview-proxy.conf']);nginx.chmod(0o644)
 subprocess.run(['nginx','-t'],check=True)
 unit.write_bytes(payload['config/shilie-preview-proxy-runtime.conf']);unit.chmod(0o644)
 subprocess.run(['systemctl','daemon-reload'],check=True);reconfigured=True
 subprocess.run(['systemctl','restart','shilie-preview'],check=True)
 for i in range(30):
  try:feed('http://127.0.0.1:18771/api/community/topics');break
  except Exception:
   if i==29:raise
   time.sleep(1)
 subprocess.run(['systemctl','reload','nginx'],check=True)
 for i in range(15):
  try:feed('https://127.0.0.1:8771/api/community/topics',ctx);break
  except Exception:
   if i==14:raise
   time.sleep(1)
 for encoding,expected in [('gzip','gzip'),('gzip;q=0',None),('*','gzip')]:
  request=urllib.request.Request('https://127.0.0.1:8771/api/community/topics',headers={'Accept-Encoding':encoding})
  with urllib.request.urlopen(request,context=ctx,timeout=5) as r:
   assert r.headers.get('Content-Encoding')==expected,(encoding,r.headers.get('Content-Encoding'))
 assert hashlib.sha256(index.read_bytes()).hexdigest()==index_hash
 assert subprocess.check_output(['systemctl','show','shilie','-p','MainPID','--value'],text=True).strip()==prod_pid
 command=subprocess.check_output(['systemctl','show','shilie-preview','-p','ExecStart','--value'],text=True)
 assert '--host 127.0.0.1 --port 18771 --workers 1' in command
 print('PASS preview nginx TLS8771 -> loopback18771; one worker; 8 native contracts; gzip opt-out/wildcard; workspace index and production PID unchanged')
except BaseException:
 nginx.unlink(missing_ok=True);unit.unlink(missing_ok=True)
 subprocess.run(['nginx','-t'],check=True);subprocess.run(['systemctl','reload','nginx'],check=True)
 for p,b in old.items():
  if b is None:p.unlink(missing_ok=True)
  else:put(p,b)
 if reconfigured:
  subprocess.run(['systemctl','daemon-reload'],check=True)
  subprocess.run(['systemctl','restart','shilie-preview'],check=True)
 raise
'''
ssh = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "IdentitiesOnly=yes",
       "-i", str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"), "root@8.156.81.128", "python3 -"]
subprocess.run(ssh, input=("payload="+repr(payload)+"\n"+script).encode(), check=True)
