from pathlib import Path
import sys,json,hashlib,shutil,tempfile,importlib.util
from datetime import datetime
from zoneinfo import ZoneInfo
root=Path.cwd();sys.path.insert(0,str(root/'src'))
from rag_tech_retriever.common.stage_journal import StageJournal
stage='20261013-101051-82857be6';art=root/'output/stages'/stage/'artifacts';preview=root/'output/web/design'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def inventory(folder): return {p.name:digest(p) for p in folder.iterdir() if p.is_file()}
def manifest(): (art/'prototype-manifest.json').write_text(json.dumps({'stage_id':stage,'before':inventory(art/'prototype-before'),'after':inventory(preview)},ensure_ascii=False,indent=2),encoding='utf-8')
manifest()
spec=importlib.util.spec_from_file_location('recover',art/'recover_prototype.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert m.restore(preview)['can_apply']
with tempfile.TemporaryDirectory() as tmp:
    target=Path(tmp)/'preview';shutil.copytree(preview,target)
    result=m.restore(target,True);assert result['restored']
    assert inventory(target)==inventory(art/'prototype-before')
with tempfile.TemporaryDirectory() as tmp:
    target=Path(tmp)/'preview';shutil.copytree(preview,target)
    p=target/'index.html';p.write_text(p.read_text(encoding='utf-8')+'\n<!-- later edit -->',encoding='utf-8');before=digest(p)
    refused=m.restore(target,True);assert not refused['can_apply'] and digest(p)==before
(art/'recovery-verification.json').write_text(json.dumps({'preview_preflight':True,'isolated_restore_exact':True,'later_edit_refused':True},indent=2),encoding='utf-8')
j=StageJournal(root,root/'output/stages')
j.finish(stage,completed=['完成紧凑工作台、双导航、横向优先级、分类折叠与详情抽屉','删除重复介绍、空指标和虚构阶段；接入真实只读阶段摘要','独立副本验证后整体替换预览，保存前后源码与恢复工具'],issues=['设计预览中的知识与任务仍为示例；流程未接入执行','部署和生产保存未在本轮验证','曾逐文件替换预览导致脚本冲突，已恢复并改为独立验证后整体替换'],verification=['最终 8770 地址 96 个页面布局和 90 个优先级/密度组合通过','键盘、抽屉焦点、故障重试、偏好撤销、减少动画通过；脚本和非预期资源错误为零','分段移动 210ms 与点击光晕实测；桌面和手机截图已查看','恢复工具预检、临时副本精确还原、拒绝后续编辑通过'])
records=[]
for row in j.list():
    records.append({k:row.get(k,[]) for k in ['id','title','status','completed','issues','verification','changes']})
    records[-1]['date']=datetime.fromisoformat(row.get('completed_at') or row['created_at']).astimezone(ZoneInfo('Asia/Taipei')).strftime('%Y-%m-%d %H:%M')
(preview/'stage-records.json').write_text(json.dumps({'records':records},ensure_ascii=False,indent=2),encoding='utf-8')
manifest();assert m.restore(preview)['can_apply']
shutil.make_archive(str(art/'prototype-after'),'zip',preview)
for name in ['redesign-final-result.json','redesign-motion-result.json','redesign-check-final.js']:
    shutil.copy2(root/'output/playwright'/name,art/name)
for p in (root/'output/playwright').glob('redesign-*.png'):shutil.copy2(p,art/p.name)
print(json.dumps({'stage':stage,'status':'passed','records':len(records),'recovery':'passed'},ensure_ascii=False))
