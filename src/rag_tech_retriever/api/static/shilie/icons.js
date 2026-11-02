export function icon(name) {
  const paths = {
    knowledge: '<path d="M4 2h9l3 3v13H4zM12 2v4h4M7 10h6M7 14h6"/>',
    search: '<circle cx="8" cy="8" r="5"/><path d="m12 12 5 5"/>',
    planning:
      '<path d="M4 2v15M4 5h8M4 14h8"/><circle cx="14" cy="5" r="2"/><circle cx="14" cy="14" r="2"/>',
    stages: '<path d="M3 8a7 7 0 1 1 1 6M3 3v5h5M10 5v5l3 2"/>',
    workflow:
      '<rect x="2" y="2" width="5" height="5" rx="1"/><rect x="12" y="12" width="5" height="5" rx="1"/><path d="M7 5h7v7M5 7v7h7"/>',
    agent:
      '<rect x="3" y="5" width="14" height="12" rx="3"/><path d="M10 2v3M7 13h6"/><circle cx="7" cy="9" r=".5"/><circle cx="13" cy="9" r=".5"/>',
    connection: '<path d="M7 3v5M13 3v5M5 8h10v2a5 5 0 0 1-10 0zM10 15v3"/>',
    backup: '<path d="M4 5h12v12H4zM2 2h16v3H2zM8 9h4"/>',
    settings:
      '<path d="M2 4h16M2 10h16M2 16h16"/><circle cx="6" cy="4" r="2"/><circle cx="13" cy="10" r="2"/><circle cx="8" cy="16" r="2"/>',
    home: '<path d="m2 9 8-7 8 7M4 8v10h12V8M8 18v-6h4v6"/>',
    task: '<circle cx="10" cy="10" r="7"/><path d="m6 10 3 3 5-6"/>',
    /* 锁：data.js 里 private 模块的 icon 就写着 "lock"，缺这一条会静默兜底成知识库书本。 */
    lock: '<rect x="4" y="9" width="12" height="9" rx="2"/><path d="M7 9V6a3 3 0 0 1 6 0v3"/>',
  };
  return `<svg class="icon" viewBox="0 0 20 20" aria-hidden="true">${paths[name] || paths.knowledge}</svg>`;
}
/* 环轨专用图标：24 网格、圆角端点、笔画内联（不依赖外部 CSS）。
   与上面 icon() 的 20 网格细线图标是两套：环轨节点是深底金图，
   需要更粗的笔画（2.1）和光学更平衡的造型，直接内联避免与 .icon 冲突。 */
export function orbitIcon(name) {
  const p = {
    knowledge: '<path d="M4 4.6h3.6A2.4 2.4 0 0 1 10 7v12.4a1.9 1.9 0 0 0-1.9-1.9H4z"/><path d="M20 4.6h-3.6A2.4 2.4 0 0 0 14 7v12.4a1.9 1.9 0 0 1 1.9-1.9H20z"/>',
    search: '<circle cx="10.8" cy="10.8" r="5.4"/><path d="m15 15 4.6 4.6"/>',
    planning: '<rect x="4" y="5.6" width="16" height="14.4" rx="2.4"/><path d="M4 10h16M8.4 3.4v3.6M15.6 3.4v3.6"/>',
    task: '<rect x="3.4" y="7.6" width="17.2" height="12" rx="2.6"/><path d="M8.8 7.6V6.2a2.2 2.2 0 0 1 2.2-2.2h2a2.2 2.2 0 0 1 2.2 2.2v1.4"/>',
    stages: '<path d="M5.6 21V3.6m0 0h11.2l-2 4.2 2 4.2H5.6"/>',
    agent: '<path d="M12 3.2l1.7 4.6 4.6 1.7-4.6 1.7L12 15.8l-1.7-4.6L5.7 9.5l4.6-1.7z"/><path d="M18.4 15.6l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    home: '<rect x="4" y="4" width="6.6" height="6.6" rx="1.8"/><rect x="13.4" y="4" width="6.6" height="6.6" rx="1.8"/><rect x="4" y="13.4" width="6.6" height="6.6" rx="1.8"/><rect x="13.4" y="13.4" width="6.6" height="6.6" rx="1.8"/>',
    workflow: '<path d="M13.2 3.2 5.6 13.6h5.6l-.8 7.2 7.6-10.4h-5.6z"/>',
    settings: '<circle cx="12" cy="12" r="3.4"/><path d="M12 2.6v2.4m0 14v2.4M2.6 12h2.4m14 0h2.4M5.4 5.4l1.7 1.7m9.8 9.8 1.7 1.7m0-13.2-1.7 1.7m-9.8 9.8-1.7 1.7"/>',
    lock: '<rect x="4.4" y="10.2" width="15.2" height="10" rx="2.6"/><path d="M8 10.2V7.4a4 4 0 0 1 8 0v2.8"/>',
  };
  const d = p[name] || p.knowledge;
  return `<svg class="sl-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
}
/* 已无调用方：2026-10-30 首页 v3 用 .sl-orbit 替换 .portal-grid 后，
   views.js 不再 import art。images 表缺 private 键（传 "private" 会静默落到
   settings 插画），属既存缺陷。若确无新增用途应整体删除；恢复调用前必须先补 private。 */
export function art(name) {
  const common = 'viewBox="0 0 140 100" fill="none" aria-hidden="true"';
  const images = {
    workspace:
      '<rect x="19" y="19" width="58" height="65" rx="5" fill="#eaf0fb"/><rect x="28" y="11" width="58" height="65" rx="5" fill="#fff" stroke="#8da4ca"/><path d="M40 29h30M40 39h21M40 49h28M40 59h15" stroke="#9aacca" stroke-width="2" stroke-linecap="round"/><path d="M102 27v48M102 35h16M102 61h16" stroke="#8b9fbd" stroke-width="1.5"/><circle cx="119" cy="35" r="7" fill="#fff" stroke="#4064d7" stroke-width="1.5"/><circle cx="119" cy="61" r="7" fill="#e9effb" stroke="#8299bf"/><path d="m116 35 2 2 4-4" stroke="#4064d7" stroke-width="1.5" stroke-linecap="round"/>',
    automation:
      '<path d="M32 27h39v22h37M32 73h39V49" stroke="#9bacc5" stroke-width="1.5"/><rect x="17" y="14" width="32" height="26" rx="5" fill="#fff" stroke="#8b9fbd"/><rect x="17" y="60" width="32" height="26" rx="5" fill="#fff" stroke="#8b9fbd"/><rect x="90" y="34" width="32" height="30" rx="5" fill="#eaf0fc" stroke="#4064d7"/><path d="M25 25h15M25 30h9M25 71h15M25 76h9" stroke="#90a3c0" stroke-width="1.5" stroke-linecap="round"/><path d="m103 43-4 6 4 6m7-12 4 6-4 6" stroke="#4064d7" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="71" cy="49" r="4" fill="#fff" stroke="#9bacc5"/>',
    settings:
      '<rect x="28" y="13" width="83" height="73" rx="8" fill="#fff" stroke="#8da4ca"/><path d="M43 33h53M43 49h53M43 65h53" stroke="#b0bed3" stroke-width="2" stroke-linecap="round"/><rect x="53" y="27" width="10" height="12" rx="3" fill="#fff" stroke="#4064d7" stroke-width="1.5"/><rect x="77" y="43" width="10" height="12" rx="3" fill="#eaf0fc" stroke="#8299bf"/><rect x="62" y="59" width="10" height="12" rx="3" fill="#fff" stroke="#8299bf"/>',
  };
  const palette = ["#b95b13", "#fff0dc", "#bd9a73"];
  const drawing = (images[name] || images.settings)
    .replace(/#(?:eaf0fb|eaf0fc|e9effb)/g, palette[1])
    .replace(/#4064d7/g, palette[0])
    .replace(
      /#(?:8da4ca|9aacca|8b9fbd|8299bf|9bacc5|90a3c0|b0bed3)/g,
      palette[2],
    );
  return `<svg class="portal-art" ${common}>${drawing}</svg>`;
}
