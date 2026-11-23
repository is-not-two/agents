"""Publish only the Vue community dependency closure; leave workspace index alone."""
import gzip
import re
import subprocess
from pathlib import Path

root=Path("shilie/dist").resolve()
pending=[root/"community.html"];files={}
while pending:
 p=pending.pop()
 if p.relative_to(root).as_posix() in files:continue
 data=p.read_bytes();name=p.relative_to(root).as_posix();files[name]=data
 if p.suffix in (".html",".js",".css"):
  for ref in re.findall(r"""["']([^"'<>]+\.(?:js|css))["']""",data.decode()):
   q=(p.parent/ref).resolve()
   if not q.is_relative_to(root) or not q.is_file():continue
   if q.relative_to(root).as_posix() not in files:pending.append(q)
files["community-reader.html"]=(root/"community-reader.html").read_bytes()
assert len(files)>=5,files.keys()
print("community files",list(files),"JS gzip bytes",sum(len(gzip.compress(v)) for k,v in files.items() if k.endswith(".js")))
script=r"""
from pathlib import Path
import tempfile,os,hashlib
root=Path("/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever/api/static/vue")
original=hashlib.sha256((root/"index.html").read_bytes()).hexdigest()
for name,data in files.items():
 p=root/name;assert p.resolve().is_relative_to(root.resolve())
 if not name.endswith(".html") and p.exists():assert p.read_bytes()==data,"asset collision"
for name,data in sorted(files.items(),key=lambda x:2 if x[0]=="community-reader.html" else 1 if x[0]=="community.html" else 0):
 p=root/name;p.parent.mkdir(exist_ok=True)
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(data);temp=f.name
 st=(root/"index.html").stat();os.chown(temp,st.st_uid,st.st_gid);os.chmod(temp,0o644);os.replace(temp,p)
 assert p.read_bytes()==data
assert hashlib.sha256((root/"index.html").read_bytes()).hexdigest()==original
print("PASS community published; workspace index unchanged; assets reopened")
"""
ssh=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"]
subprocess.run(ssh,input=("files="+repr(files)+chr(10)+script).encode(),check=True)
