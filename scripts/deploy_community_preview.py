import subprocess
from pathlib import Path

root=Path("src/rag_tech_retriever/api")
main=(root/"main.py").read_text(encoding="utf-8")
block=main[main.index("    community_origin ="):main.index("    application.state.context = context")]
line=next(x for x in main.splitlines() if "and not (community_origin" in x)
router=(root/"routes/community.py").read_bytes()
pre="block="+repr(block)+"\nline="+repr(line)+"\nraw="+repr(router)+"\n"
script=r"""
from pathlib import Path
import subprocess,os,time,urllib.request,ssl
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError
unit="shilie-preview"
def cmd(*s):return subprocess.check_output(s,text=True).strip()
assert cmd("systemctl","show",unit,"-p","User","--value")=="shilie_pvapp"
assert cmd("systemctl","show",unit,"-p","WorkingDirectory","--value")=="/var/lib/shilie-preview/app"
api=Path("/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever/api")
p=api/"main.py";r=api/"routes/community.py";drop=Path("/etc/systemd/system/shilie-preview.service.d/zzzzz-community-origin.conf")
assert not drop.exists() and not r.exists()
old=p.read_bytes();s=old.decode()
anchor='            and request.url.path != "/api/session"'
key='    application.state.context = context'
assert s.count(anchor)==1 and s.count(key)==1 and "community_endpoints" not in s
new=s.replace(anchor,anchor+"\n"+line).replace(key,block+key).encode();compile(new,str(p),"exec");compile(raw,str(r),"exec")
def write(path,data,mode):
 with NamedTemporaryFile(dir=path.parent,delete=False) as f:
  f.write(data);tmp=f.name
 if path.exists(): os.chown(tmp,path.stat().st_uid,path.stat().st_gid)
 os.chmod(tmp,mode);os.replace(tmp,path)
def restart():
 subprocess.run(["systemctl","daemon-reload"],check=True);subprocess.run(["systemctl","restart",unit],check=True)
def probe(path):
 with urllib.request.urlopen("https://127.0.0.1:8771"+path,context=ssl._create_unverified_context(),timeout=3) as resp:return resp.read()
mode=p.stat().st_mode&0o777
try:
 write(r,raw,0o644);write(p,new,mode);drop.parent.mkdir(exist_ok=True);write(drop,b"[Service]\nEnvironment=COMMUNITY_PUBLIC_ORIGIN=https://8.156.81.128:8771\n",0o644);restart()
 for i in range(35):
  try:
   import json
   assert isinstance(json.loads(probe("/api/community/topics"))["items"],list)
   assert json.loads(probe("/api/community/search?q=Excel"))["mode"]=="keyword"
   try:probe("/api/admin/stats")
   except HTTPError as e:assert e.code==401
   else:raise ValueError("private API unexpectedly public")
   print("PASS 8771 live feed/search; private stats unauthenticated 401");break
  except Exception as e:
   if i==34:raise
   time.sleep(1)
except BaseException:
 write(p,old,mode);r.unlink(missing_ok=True);drop.unlink(missing_ok=True);restart();raise
"""
ssh=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-o","IdentitiesOnly=yes","-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"]
subprocess.run(ssh,input=(pre+script).encode(),check=True)


