/* Invoked only by playwright-cli against a UUID-verified disposable Vue server. */
async page => {
  const base = __BASE_URL__, runId = __RUN_ID__, phase = __PHASE__;
  const check = (value, label) => { if (!value) throw Error(label); };
  const go = route => page.goto(base + '/#/' + route);
  const api = path => page.evaluate(async path => {
    const r = await fetch(path, { cache: 'no-store' });
    return { status: r.status, data: await r.json() };
  }, path);
  if (!page.url().startsWith(base + '/')) await go('module/knowledge');
  check((await api('/__qa__/identity')).data.run_id === runId, 'Unexpected server; abort before mutations');
  page.setDefaultTimeout(12000);
  const errors = [];
  const onError = error => errors.push(error.message);
  page.on('pageerror', onError);
  const get = (role, name) => page.getByRole(role, { name, exact: true });
  const noteLink = name => page.getByRole('link').filter({ has: get('heading', name) });
  const editor = page.locator('form').filter({ has: page.getByRole('textbox', { name: '正文', exact: true }) });
  const draftTitle = '断连时保留输入 ' + runId;
  const noteTitle = 'Vue 回归笔记 ' + runId;
  const savedText = 'Vue 修改版：重载后保持。';
  const password = 'isolated-regression-only';
  async function notes() {
    const r = await api('/api/knowledge');
    check(r.status === 200, 'Note read failed');
    return r.data;
  }
  const save = () => editor.getByRole('button', { name: '保存', exact: true }).click();
  async function fillNote(title, text) {
    await get('button', '新建笔记').click();
    await editor.getByLabel('标题', { exact: true }).fill(title);
    await editor.getByLabel('正文', { exact: true }).fill(text);
  }
  try {
    switch (phase) {
      case 'core': {
        await page.setViewportSize({ width: 1440, height: 1000 });
        check((await api('/legacy')).status === 404, 'Legacy HTTP entry still served');
        await go('');
        await get('link', '开始').waitFor();
        check(await page.locator('.workspace-sidebar').count() === 0, 'Start has a sidebar');
        await get('link', '开始').click();
        await page.locator('.workspace-sidebar').waitFor();
        await go('module/knowledge');
        await fillNote(noteTitle, 'Vue 新建版。');
        await save();
        await noteLink(noteTitle).click();
        await get('button', '编辑').click();
        await editor.getByLabel('正文', { exact: true }).fill(savedText);
        await save();
        await page.getByText(savedText, { exact: true }).waitFor();
        await page.reload();
        await page.getByText(savedText, { exact: true }).waitFor();
        await get('button', '查看版本历史').click();
        await get('heading', '版本历史').waitFor();
        const row = (await notes()).find(note => note.data.title === noteTitle);
        check(row?.version === 2, 'Note not persisted at version two');
        check((await api('/api/records/' + row.id + '/history')).data.length === 2, 'History missing');
        await go('module/job-flow/manage');
        await get('heading', '单表管理').waitFor();
        for (const [route, name] of [
          ['planning', '人生规划'], ['job-flow', '求职流水线'], ['learning', '到期复习'],
          ['job-insights', '岗位证据对照'], ['agent-studio', 'Agent 工作室'],
          ['collaboration', 'Agent 协作'], ['documents', '技术文档检索'], ['backup', '数据与备份'],
        ]) {
          await go('module/' + route);
          await page.getByRole('heading', { name, exact: true, level: 1 }).waitFor();
        }
        await go('module/private');
        await page.getByLabel('新口令', { exact: true }).fill(password);
        await page.getByLabel('再次输入口令', { exact: true }).fill(password);
        await get('button', '保存私密口令').click();
        await page.getByLabel('私密口令', { exact: true }).fill(password);
        await get('button', '解锁').click();
        await get('button', '添加愿望').click();
        await page.getByLabel('标题', { exact: true }).fill('隔离愿望 ' + runId);
        await get('button', '保存').click();
        await get('heading', '隔离愿望 ' + runId).waitFor();
        await get('button', '锁定此页面').click();
        await get('heading', '解锁愿望与日记').waitFor();
        await page.setViewportSize({ width: 390, height: 844 });
        await go('module/knowledge');
        await get('button', '新建笔记').waitFor();
        check(await page.evaluate(() => document.documentElement.scrollWidth <= 390), 'Mobile layout overflow');
        break;
      }
      case 'prepare-failure':
        await go('module/knowledge');
        await fillNote(draftTitle, '数据库恢复后保存。');
        break;
      case 'database-offline': {
        await save();
        await editor.getByRole('alert').filter({ hasText: '数据库暂不可用' }).waitFor();
        check(await editor.getByLabel('标题', { exact: true }).inputValue() === draftTitle, 'Draft lost');
        const response = await api('/health');
        check(response.status === 503 && !JSON.stringify(response.data).includes('password'), 'Unsafe outage response');
        break;
      }
      case 'database-recovered':
        await save();
        await noteLink(draftTitle).waitFor();
        check((await notes()).filter(note => note.data.title === draftTitle).length === 1, 'Retry lost or duplicated note');
        break;
      case 'application-restarted':
        await page.reload();
        await noteLink(draftTitle).waitFor();
        await go('module/private');
        await page.getByLabel('私密口令', { exact: true }).fill(password);
        await get('button', '解锁').click();
        await get('heading', '隔离愿望 ' + runId).waitFor();
        break;
      default: throw Error('Unknown Vue regression phase');
    }
    check(errors.length === 0, 'Browser error: ' + errors.join('; '));
    return { passed: true, phase };
  } finally {
    page.off('pageerror', onError);
  }
}
