// 统一 HTTP 请求与可识别错误；不管理页面和领域规则。
export async function api(path, method = 'GET', payload) {
  const response = await fetch('/api' + path, {method, headers: payload === undefined ? {} : {'Content-Type':'application/json'}, body:payload === undefined ? undefined : JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401) document.dispatchEvent(new Event('workspace:unauthorized'));
    const message = typeof data.detail === 'string' ? data.detail : '提交格式有误，请检查表单';
    throw new Error(message);
  }
  return data;
}
