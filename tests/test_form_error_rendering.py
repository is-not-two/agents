"""表单错误提示的 DOM 父子关系回归；不连接数据库或读取用户配置。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = (Path(__file__).resolve().parents[1]
          / "src/rag_tech_retriever/api/static/shilie/app.js")

# 最小 DOM 替身保留 insertBefore 的父子约束；真实浏览器验收另记于协作日志。
PROBE = r"""
const fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('function showFormError(');
const end = source.indexOf('\nfunction showConflict(', start);
if (start < 0 || end < 0) throw new Error('showFormError site missing');
class Node {
  constructor(className = '') { this.className = className; this.children = []; }
  append(node) {
    if (node.parentElement) node.remove();
    this.children.push(node); node.parentElement = this;
  }
  insertBefore(node, ref) {
    if (ref === null) return this.append(node);
    if (ref.parentElement !== this) throw new Error('NotFoundError');
    if (node.parentElement) node.remove();
    this.children.splice(this.children.indexOf(ref), 0, node); node.parentElement = this;
  }
  before(node) { this.parentElement.insertBefore(node, this); }
  remove() {
    this.parentElement.children.splice(this.parentElement.children.indexOf(this), 1);
    this.parentElement = null;
  }
  setAttribute(key, value) { this[key] = value; }
  querySelector(selector) {
    for (const child of this.children) {
      if (child.className.split(' ').includes(selector.slice(1))) return child;
      const match = child.querySelector(selector); if (match) return match;
    }
    return null;
  }
}
const sandbox = {document: {createElement: () => new Node()}};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end) + '\nthis.showFormError = showFormError;', sandbox);
const results = {};
for (const placement of ['nested', 'direct', 'absent']) {
  const form = new Node(), drawer = new Node('drawer-content');
  const actions = new Node('form-actions');
  form.append(drawer);
  if (placement !== 'absent') (placement === 'nested' ? drawer : form).append(actions);
  sandbox.showFormError(form, '<img src=x onerror=alert(1)>');
  const alert = form.querySelector('.form-error');
  const initial = alert.textContent === '<img src=x onerror=alert(1)>' && alert.role === 'alert';
  const correctParent = alert.parentElement === (placement === 'nested' ? drawer : form);
  const beforeActions = placement === 'absent' || actions.parentElement.children.indexOf(alert)
    === actions.parentElement.children.indexOf(actions) - 1;
  sandbox.showFormError(form, 'conflict');
  const reused = form.querySelector('.form-error') === alert && alert.textContent === 'conflict';
  sandbox.showFormError(form);
  sandbox.showFormError(form);
  results[placement] = {initial, correctParent, beforeActions, reused,
    cleared: form.querySelector('.form-error') === null};
}
process.stdout.write(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def form_error_results() -> dict:
    """在 Node 内执行实际 showFormError，避免把业务函数复制进测试。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("需要 Node 执行前端纯逻辑回归")
    result = subprocess.run(
        [node, "-e", PROBE, str(SOURCE)], capture_output=True, text=True,
        encoding="utf-8", timeout=10, check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("placement", ["nested", "direct", "absent"])
def test_form_error_parent_update_and_clear(form_error_results: dict, placement: str) -> None:
    """嵌套/直接/缺少操作区均可提示、复用节点、清错，且不解释消息为 HTML。"""
    assert form_error_results[placement] == {
        "initial": True,
        "correctParent": True,
        "beforeActions": True,
        "reused": True,
        "cleared": True,
    }
