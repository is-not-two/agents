import hashlib,json,re,ssl,time,urllib.parse,urllib.request
from pathlib import Path
root=Path(r'E:\project\agents\rag-tech-doc-retriever');out=root/'output/verification/preview-compare-20261105';p=out/'comparison.json';data=json.loads(p.read_text(encoding='utf8'));local=root/'src/rag_tech_retriever/api/static/shilie';candidate=root/'output/frontend-redesign-20261104/candidate/src/rag_tech_retriever/api/static/shilie';o=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
normalize=lambda b:re.sub(rb'([?&]v=)11[56]\b',rb'\1VERSION',b.replace(b'\r\n',b'\n'))
for row in data['items']:
 if row['http_status']!=200 or not (row['local_comparison']=='different' or row['candidate_comparison']=='different'):continue
 name=row['file'];url='https://8.156.81.128:8771/'+('' if name=='index.html' else 'static/shilie/'+urllib.parse.quote(name));remote=o.open(url,timeout=5).read();assert hashlib.sha256(remote).hexdigest()==row['server_sha256'],name
 for label,base in [('local',local),('candidate',candidate)]:
  path=base/name
  if path.is_file():row[label+'_normalized_compare']='equal_ignoring_crlf_and_v115_v116' if normalize(remote)==normalize(path.read_bytes()) else 'different_after_normalization'
 time.sleep(.12)
p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
for label in ('local','candidate'):
 print(label)
 for state in ('equal_ignoring_crlf_and_v115_v116','different_after_normalization'):
  files=[x['file'] for x in data['items'] if x.get(label+'_normalized_compare')==state];print(state,len(files),', '.join(files))
