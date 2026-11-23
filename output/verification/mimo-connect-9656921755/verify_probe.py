import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("mimo_probe",sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def run(url,model,mode):
 seen={}
 def fake(cfg,body,timeout,limit):
  seen.update(body)
  if mode=="401":raise m.ProviderError("redacted",status=401)
  if mode=="malformed":return {"choices":[]}
  if model.startswith("mimo-v2.6") and body.get("thinking")!={"type":"disabled"}:return {"choices":[{"message":{"content":""},"finish_reason":"length"}]}
  return {"choices":[{"message":{"content":"OK"}}]}
 m.post_chat=fake
 c=m.ModelConnection(Path("never-written.json"));c.load=lambda:{"api_key":"fake","base_url":url,"model":model,"revision":"test","source":"web"}
 return c.test({}),seen
for label,url,model,mode in [("mimo","https://token-plan-cn.xiaomimimo.com/v1","mimo-v2.6-flash","normal"),("other-provider","https://example.com/v1","demo","normal"),("malformed","https://example.com/v1","demo","malformed"),("denied","https://example.com/v1","demo","401")]:
 result,body=run(url,model,mode);print(label,"ok="+str(result["ok"]),"thinking="+str(body.get("thinking")),"message="+result["message"])
