"""Deploy public rating explanation to preview without exposing historical notes."""
from pathlib import Path
import subprocess
ui=Path("shilie/public/community-reader.html").read_bytes()
script=r'''
from pathlib import Path
import subprocess,tempfile,os,ssl,urllib.request,json,time
root=Path("/var/lib/shilie-preview/app/.venv312/lib/python3.12/site-packages/rag_tech_retriever")
route=root/"api/routes/community.py";page=root/"api/static/vue/community-reader.html"
old={p:p.read_bytes() for p in (route,page)};s=old[route].decode()
a='    rationale: str = Field(min_length=1, max_length=2000)'
assert s.count(a)==1 and 'public_rationale: bool' not in s
s=s.replace(a,a+chr(10)+'    public_rationale: bool = False')
a='community.reviews(post_id,reviewer_id,version,score,rationale)';assert s.count(a)==1
s=s.replace(a,'community.reviews(post_id,reviewer_id,version,score,rationale,rationale_public)')
a='VALUES(%s,%s,%s,%s,%s)""",(str(data.post_id),reviewer["id"],data.version,data.score,data.rationale.strip()))';assert s.count(a)==1
s=s.replace(a,'VALUES(%s,%s,%s,%s,%s,%s)""",(str(data.post_id),reviewer["id"],data.version,data.score,data.rationale.strip(),data.public_rationale))')
a='                return {"item":row}';assert s.count(a)==1
s=s.replace(a,'                cur.execute("SELECT score,rationale,reviewed_at FROM community.public_review_evidence WHERE post_id=%s",(str(topic),))'+chr(10)+'                return {"item":{**row,"review":cur.fetchone()}}')
compile(s,str(route),"exec")
def put(p,data):
 st=p.stat()
 with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(data);name=f.name
 os.chown(name,st.st_uid,st.st_gid);os.chmod(name,st.st_mode&0o777);os.replace(name,p)
try:
 put(route,s.encode());put(page,ui)
 subprocess.run(["systemctl","restart","shilie-preview"],check=True)
 ctx=ssl.create_default_context(cafile="/var/lib/shilie-preview/app/credentials/server.crt");ctx.check_hostname=False
 for i in range(30):
  try:
   with urllib.request.urlopen("https://127.0.0.1:8771/api/community/topics",context=ctx,timeout=3) as r:assert isinstance(json.load(r)["items"],list)
   print("PASS preview restarted; existing feed available; new rating UI published",flush=True);break
  except Exception:
   if i==29:raise
   time.sleep(1)
except BaseException:
 for p,data in old.items():put(p,data)
 subprocess.run(["systemctl","restart","shilie-preview"],check=True)
 raise
'''
ssh=["ssh","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-i",str(Path.home()/".ssh/selfstock_8_156_81_128_rsa"),"root@8.156.81.128","python3 -"]
subprocess.run(ssh,input=("ui="+repr(ui)+chr(10)+script).encode(),check=True)
