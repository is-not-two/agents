"""Bound preview limiter memory; retain original quota and single-process runtime."""
import subprocess
from pathlib import Path

source=Path('src/rag_tech_retriever/common/middleware/rate_limiter.py').read_bytes()
roles=Path(Path('output/community-vue/rate-roles-path.txt').read_text(encoding='utf-8'))
assert (roles/'MODIFIED_FILE.py').read_bytes()==source
tests=Path('tests/test_rate_limit_bounds.py').read_bytes()
script=r'''
from pathlib import Path
import os,subprocess,tempfile,time,ssl,urllib.request,json,hashlib
root=Path('/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever')
module=root/'common/middleware/rate_limiter.py';main=root/'api/main.py'
old={p:p.read_bytes() for p in (module,main)}
assert hashlib.sha256(old[module]).hexdigest()=='34bbe7f581e5b837d09de599eca66a2cb548cab0718110da8474f55833d13bdc'
from rag_tech_retriever.common.middleware.rate_limiter import SlidingWindowLimiter
baseline=SlidingWindowLimiter(600,60)
for n in range(1000):baseline.allow(str(n),now=0)
for n in range(1000,2000):baseline.allow(str(n),now=61)
assert len(baseline._hits)==2000
print('BASELINE native expired-visitor keys retained:2000',flush=True)
text=old[main].decode();needle='        window_seconds=60,'
assert text.count(needle)==1 and 'WEB_RATE_LIMIT_MAX_EVENTS' not in text
text=text.replace(needle,needle+'\n        max_clients=int(settings.env("WEB_RATE_LIMIT_MAX_CLIENTS",str(config.get("web.rate_limit_max_clients",4096)))),\n        max_events=int(settings.env("WEB_RATE_LIMIT_MAX_EVENTS",str(config.get("web.rate_limit_max_events",131072)))),')
compile(text,str(main),'exec');compile(source,str(module),'exec')
prod_pid=subprocess.check_output(['systemctl','show','shilie','-p','MainPID','--value'],text=True).strip()
index=root/'api/static/vue/index.html';index_hash=hashlib.sha256(index.read_bytes()).hexdigest()
def put(p,data):
 st=p.stat()
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(data);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,p)
restarted=False
try:
 put(module,source);put(main,text.encode())
 with tempfile.TemporaryDirectory(prefix='preview-rate-bounds-') as folder:
  f=Path(folder)/'test_bounds.py';f.write_bytes(tests)
  subprocess.run(['/var/lib/shilie-preview/app/.venv312/bin/python',str(f)],check=True)
 subprocess.run(['systemctl','restart','shilie-preview'],check=True);restarted=True
 ctx=ssl.create_default_context(cafile='/var/lib/shilie-preview/app/credentials/server.crt');ctx.check_hostname=False
 for n in range(30):
  try:
   with urllib.request.urlopen('https://127.0.0.1:8771/api/community/topics',context=ctx,timeout=4) as r:assert r.status==200 and isinstance(json.load(r)['items'],list)
   break
  except Exception:
   if n==29:raise
   time.sleep(1)
 pid=subprocess.check_output(['systemctl','show','shilie-preview','-p','MainPID','--value'],text=True).strip()
 env=dict(v.split('=',1) for v in Path('/proc',pid,'environ').read_bytes().decode().split(chr(0)) if '=' in v)
 assert env['POSTGRES_DB']=='shilie_preview_20261104' and env['POSTGRES_PORT']=='55433'
 assert env['WEB_RATE_LIMIT_PER_MINUTE']=='600'
 os.environ.update(env)
 from rag_tech_retriever.common.config_loader import ConfigLoader
 settings=ConfigLoader.load_default();config=ConfigLoader(settings.settings_path.parent/'web.yaml')
 effective={'max_clients':int(settings.env('WEB_RATE_LIMIT_MAX_CLIENTS',str(config.get('web.rate_limit_max_clients',4096)))),
            'max_events':int(settings.env('WEB_RATE_LIMIT_MAX_EVENTS',str(config.get('web.rate_limit_max_events',131072))))}
 assert effective=={'max_clients':4096,'max_events':131072},effective
 assert hashlib.sha256(index.read_bytes()).hexdigest()==index_hash
 assert subprocess.check_output(['systemctl','show','shilie','-p','MainPID','--value'],text=True).strip()==prod_pid
 assert module.read_bytes()==source
 print('PASS preview limiter9 contracts; per-IP600/min unchanged; configured',json.dumps(effective),'; feed200; workspace index and production PID unchanged')
except BaseException:
 for p,b in old.items():put(p,b)
 if restarted:subprocess.run(['systemctl','restart','shilie-preview'],check=True)
 raise
'''
ssh=['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes',
     '-i',str(Path.home()/'.ssh/selfstock_8_156_81_128_rsa'),'root@8.156.81.128','/var/lib/shilie-preview/app/.venv312/bin/python -']
subprocess.run(ssh,input=('source='+repr(source)+'\ntests='+repr(tests)+'\n'+script).encode(),check=True)
