import {state} from '../state.js';
import {$,esc,date,button,heading,empty,badge,icon} from '../ui.js';
export function knowledgeCards() {
  const term=state.filter.toLowerCase();
  const rows=state.knowledge.filter(row=>[row.data.title,row.data.content,...row.data.tags].join(' ').toLowerCase().includes(term));
  if(!rows.length) return empty('knowledge',state.trash?'回收站暂无知识':state.filter?'未找到匹配内容':'知识库暂无内容',state.filter?'调整筛选条件后重试。':'通过网页录入笔记、经验和文档摘要。保存后可以检索与恢复历史版本。',state.trash?'':button('新建知识','knowledge-new'));
  return `<table class="list-table"><thead><tr><th>标题与内容</th><th class="tag-col" style="width:155px">标签</th><th class="time-col" style="width:120px">更新时间</th><th class="actions-col" style="width:128px;text-align:right">操作</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${button(esc(row.data.title),'knowledge-view',row.id,'','row-title')}<p class="row-excerpt">${esc(row.data.content.slice(0,100))}</p></td><td class="tag-col"><div class="tags">${row.data.tags.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div></td><td class="time-col row-time">${date(row.updated_at)}<br><small>版本 ${row.version}</small></td><td class="actions-col"><div class="row-actions">${state.trash?button('恢复','history',row.id,'data-kind="knowledge"','text-button'):button('编辑','knowledge-edit',row.id,'','text-button')+button('历史','history',row.id,'data-kind="knowledge"','text-button')}</div></td></tr>`).join('')}</tbody></table>`;
}
export function knowledgePage() {
  return heading('知识库','录入、整理和检索个人知识。每次修改都有历史版本。',button('导出','export')+button('新建知识','knowledge-new','','','primary')) +
    `<div class="toolbar"><input class="filter-input" id="filter" value="${esc(state.filter)}" placeholder="筛选标题、正文或标签" aria-label="筛选知识"><label class="toggle-label"><input type="checkbox" id="trash" ${state.trash?'checked':''}>查看回收站</label></div><div id="filtered">${knowledgeCards()}</div>`;
}
