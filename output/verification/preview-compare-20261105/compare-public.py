import difflib,hashlib,json,ssl,time,urllib.error,urllib.parse,urllib.request
from pathlib import Path
root=Path(r'E:\project\agents\rag-tech-doc-retriever');folder=root/'output/verification/preview-compare-20261105';local=root/'src/rag_tech_retriever/api/static/shilie';candidate=root/'output/frontend-redesign-20261104/candidate/src/rag_tech_retriever/api/static/shilie'
sha=lambda b:hashlib.sha256(b).hexdigest();ctx=ssl._create_unverified_context();opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx));names=sorted({p.name for d in (local,candidate) for p in d.iterdir() if p.is_file() and p.suffix in {'.js','.css','.html'}});items=[]
for name in names:
 url='https://8.156.81.128:8771/'+('' if name=='index.html' else 'static/shilie/'+urllib.parse.quote(name))
 req=urllib.request.Request(url,headers={'Cache-Control':'no-cache','User-Agent':'Shilie-readonly-compare/1.0'})
 try:
  with opener.open(req,timeout=5) as response:
   status=response.status;typ=response.headers.get('Content-Type','');remote=response.read(3000001)
   if len(remote)>3000000:raise ValueError('response size limit exceeded')
 except urllib.error.HTTPError as e:
  status=e.code;typ=e.headers.get('Content-Type','');remote=None
 except Exception as e:
  status=None;typ=type(e).__name__+': '+str(e);remote=None
 entry={'file':name,'http_status':status,'content_type':typ,'server_sha256':sha(remote) if remote is not None else None}
 for label,base in [('local',local),('candidate',candidate)]:
  p=base/name;data=p.read_bytes() if p.is_file() else None;entry[label+'_sha256']=sha(data) if data is not None else None
  entry[label+'_comparison']='absent_locally' if data is None else ('server_404' if status==404 else ('unverified_http' if remote is None or status!=200 or ('text/html' in typ and name!='index.html') else ('identical' if data==remote else 'different')))
  if remote is not None and status==200 and data is not None and entry[label+'_comparison']=='different':
   try:
    ops=list(difflib.SequenceMatcher(None,remote.decode('utf8').splitlines(),data.decode('utf8').splitlines(),autojunk=True).get_opcodes());entry[label+'_line_changes']={'server_lines_removed_or_changed':sum(b-a for tag,a,b,c,d in ops if tag!='equal'),'local_lines_added_or_changed':sum(d-c for tag,a,b,c,d in ops if tag!='equal')}
   except UnicodeDecodeError:pass
 items.append(entry);print(name, status, flush=True);time.sleep(.12)
report={'scope':'Unauthenticated GET of public top-level HTML/JS/CSS on 8771 only; compare local working tree and separate candidate; no production, no server filesystem, database, or authenticated data','tls':'certificate verification disabled: content integrity/server HTTPS identity not established by this request','items':items};(folder/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
for label in ('local','candidate'):
 print(label, {x:sum(1 for a in items if a[label+'_comparison']==x) for x in sorted({a[label+'_comparison'] for a in items})})
print('differences:')
for a in items:
 if a['local_comparison']!='identical' or a['candidate_comparison']!='identical':print(a['file'],'http='+str(a['http_status']),'local='+a['local_comparison'],'candidate='+a['candidate_comparison'])
print('report:',folder/'comparison.json')
