/* Unsaved public notes/bookmarks: memory-only checks, never browser persistence. */
const clean = new WeakMap();
const protectedDialog = (dialog) => dialog?.matches('dialog[data-form="knowledge"],dialog[data-form="bookmark"]');
function signature(dialog) {
  return JSON.stringify([...dialog.querySelector('form').elements]
    .filter(e => e.name && !['submit', 'button'].includes(e.type))
    .map(e => [e.name, e.type === 'checkbox' || e.type === 'radio' ? e.checked : e.value]));
}
export function markDraftClean(dialog) {
  if (protectedDialog(dialog)) clean.set(dialog, signature(dialog));
}
export function draftIsDirty(dialog) {
  return protectedDialog(dialog) && clean.has(dialog) && clean.get(dialog) !== signature(dialog);
}
export function allowDraftClose(dialog) {
  if (protectedDialog(dialog) && dialog.dataset.draftSaving === 'true') return false;
  if (!draftIsDirty(dialog)) return true;
  const name = dialog.dataset.form === 'knowledge' ? '笔记' : '收藏';
  if (!window.confirm(`${name}有未保存的修改。确定放弃这些修改吗？选择取消可继续编辑。`)) return false;
  markDraftClean(dialog);
  return true;
}
export function setDraftSaving(dialog, saving) {
  if (protectedDialog(dialog)) dialog.dataset.draftSaving = String(saving);
}
const watched = new WeakSet();
export function watchDraft(dialog) {
  if (!protectedDialog(dialog)) return;
  markDraftClean(dialog);
  if (watched.has(dialog)) return;
  watched.add(dialog);
  dialog.addEventListener('cancel', event => {
    if (!allowDraftClose(dialog)) event.preventDefault();
  });
}
export function allowDraftNavigation() {
  return [...document.querySelectorAll('dialog[open]')].every(allowDraftClose);
}
window.addEventListener('beforeunload', event => {
  if ([...document.querySelectorAll('dialog[open]')].some(draftIsDirty)) {
    event.preventDefault();
    event.returnValue = '';
  }
});
