import {state} from '../state.js';
import {api} from '../api.js';
import {$,esc,date,button,toast} from '../ui.js';
import {showDialog,field,textarea,confirmation} from './shared.js';
export function stageDialog() {
  showDialog('开始一个大阶段',field('阶段名称','title','','text',true)+textarea('目标与范围','objective','',5)+`<p class="subtitle">开始时保存源码快照与当前知识/规划。结束时再记录成果、问题和验证。</p>`,async f=>{await api('/stages','POST',{title:f.elements.title.value,objective:f.elements.objective.value});toast('阶段已开始，快照已保存');},'开始并保存快照');
}
export function stageFinish(id) {
  const row=state.stages.find(s=>s.id===id);
  showDialog('记录结果 · '+row.title,textarea('完成了什么（每行一项）','completed','',4)+textarea('问题与处理（每行一项）','issues','',3)+textarea('怎么验证 / 证据位置（每行一项）','verification','',4)+`<label class="field">阶段结果<select name="status"><option value="passed">已验证完成</option><option value="attention">仍有问题 / 待处理</option></select></label>`,async f=>{
    const lines=name=>f.elements[name].value.split('\n').map(s=>s.trim()).filter(Boolean);
    if(f.elements.status.value==='passed'&&!lines('verification').length) throw new Error('请填写验证证据，或选择仍待处理');
    await api('/stages/'+id+'/finish','POST',{completed:lines('completed'),issues:lines('issues'),verification:lines('verification'),status:f.elements.status.value});toast('阶段结果与文件改动已保存');
  },'保存阶段结果');
}
export async function stageDetails(id) {
  const row=state.stages.find(s=>s.id===id), response=await fetch('/api/stages/'+id+'/diff'), patch=await response.text();
  showDialog('文件改动 · '+row.title,`<p class="subtitle">${row.changes.length} 个文件 · 实现前快照保存在阶段目录</p><ul class="change-list">${row.changes.map(c=>`<li>${esc(({added:'新增',modified:'修改',deleted:'删除'})[c.kind])} ${esc(c.path)}</li>`).join('')}</ul><h3>文本差异</h3><pre class="code">${esc(patch)}</pre>`);
}
export async function stageCheck(id) {
  const result=await api('/stages/'+id+'/rollback-check');
  showDialog('源码回滚预检',`<p class="text-block">${result.can_apply?'检查通过：当前源码与本阶段结束时一致，可按下方命令恢复阶段前源码。':'检测到后续改动或损坏备份，回滚会拒绝覆盖。'}</p>${result.conflicts.length?`<div class="notice">${result.conflicts.map(esc).join('<br>')}</div>`:''}<p class="subtitle">本次只是预检。源码与数据库分开恢复，先确认本地服务已停止。</p><pre class="code">.venv\\Scripts\\python.exe scripts\\stage_checkpoint.py rollback --id ${esc(id)}
# 确认预检结果后，增加 --apply 执行
.venv\\Scripts\\python.exe scripts\\stage_checkpoint.py rollback --id ${esc(id)} --apply</pre>`);
}
export function restoreStage(id) {
  showDialog('恢复阶段开始时的数据',`<p class="text-block">知识和规划将恢复到该阶段开始时；此后的新增内容进入回收站。操作前会自动保留一份保护快照，已有历史版本也会保留。</p>${field('输入“恢复数据”确认','confirmation','','text',true)}`,async f=>{if(f.elements.confirmation.value!=='恢复数据')throw new Error('请输入恢复数据');const result=await api('/stages/'+id+'/restore-data','POST',{confirmation:'恢复数据'});state.trash=false;toast(`已恢复 ${result.restored_records} 条，保护快照已保存`);},'恢复并保留当前快照');
}
export function exportDialog() {
  showDialog('导出与备份',`<p class="text-block">下载到你的电脑，并在当前应用的导出目录留存一份副本。JSON 包含知识、规划、历史版本与阶段记录；Markdown 便于阅读。</p><div class="heading-actions" style="margin:20px 0"><a class="primary" href="/api/export?format=json" download>下载 JSON 备份 ↧</a><a class="secondary" href="/api/export?format=markdown" download>下载 Markdown ↧</a></div><small class="muted">应用留存位置：${esc(state.stats.export_directory)}</small><hr style="border:0;border-top:1px solid var(--line);margin:23px 0"><h3>从 JSON 恢复内容</h3><p class="subtitle">恢复内容会形成新版本，未包含的现有内容进入回收站。当前历史保留。完整数据库迁移请使用部署说明中的数据库备份。</p><label class="field" style="margin-top:17px">选择知行 JSON 文件<input type="file" name="backup" accept=".json,application/json" required></label>${field('输入“恢复数据”确认','confirmation','','text',true)}`,async f=>{if(f.elements.confirmation.value!=='恢复数据')throw new Error('请输入恢复数据');const file=f.elements.backup.files[0];if(file.size>2*1024*1024)throw new Error('文件超过 2 MB，请使用数据库备份或调整应用限制');const snapshot=JSON.parse(await file.text());await api('/import','POST',{snapshot,confirmation:'恢复数据'});state.trash=false;toast('内容已恢复，导入前快照已保存');},'恢复 JSON 内容');
}
