/* One persistent WebGL canvas for the start page; existing DOM links remain interactive. */
import { MOTION_CONFIG as config } from './motion-config.js?v=118';

const canvas = document.getElementById('temporal-canvas');
const button = document.getElementById('motion-toggle');
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const wide = matchMedia(`(min-width: ${config.minViewportWidth}px)`);
let stage = null, gl = null, program = null, buffer = null, raf = 0, scene = 'orbit';
let attempted = false, events = null, lastPaint = 0, started = 0, enteredAt = 0, yaw = 0, pitch = 0;
let cameraZoom = 1, cameraAlpha = 1;
let dragging = false, lastX = 0, lastY = 0;
let enabled = true;
try { enabled = localStorage.getItem('shilie:motion') !== 'off'; } catch { /* optional preference */ }

function syncToggle() {
  document.documentElement.dataset.motion = enabled ? 'on' : 'off';
  document.documentElement.style.setProperty('--motion-enter-duration', `${config.enterMilliseconds}ms`);
  button.textContent = enabled ? '关闭动效' : '开启动效';
  button.setAttribute('aria-pressed', String(!enabled));
  document.querySelectorAll('.sea-breeze video').forEach(video => {
    if (!enabled || reduced.matches) video.pause();
    else video.play().catch(() => { video.dataset.playback = 'unavailable'; });
  });
}
syncToggle();
button.addEventListener('click', () => {
  enabled = !enabled;
  try { localStorage.setItem('shilie:motion', enabled ? 'on' : 'off'); } catch { /* optional preference */ }
  syncToggle();
  window.dispatchEvent(new Event('shilie:motionchange'));
  schedule();
});

function shader(type, source) {
  const value = gl.createShader(type);
  gl.shaderSource(value, source);
  gl.compileShader(value);
  if (!gl.getShaderParameter(value, gl.COMPILE_STATUS)) throw Error('shader compilation failed');
  return value;
}
function initialize() {
  if (attempted) return Boolean(gl && program);
  attempted = true;
  try {
    gl = canvas.getContext('webgl', { alpha: true, antialias: true, depth: false });
    if (!gl) return false;
    const vertex = shader(gl.VERTEX_SHADER, `attribute vec2 p; attribute vec4 c; attribute float s;
      varying vec4 color; void main(){gl_Position=vec4(p,0.,1.);gl_PointSize=s;color=c;}`);
    const fragment = shader(gl.FRAGMENT_SHADER, `precision mediump float; varying vec4 color;
      void main(){gl_FragColor=color;}`);
    program = gl.createProgram();
    gl.attachShader(program, vertex); gl.attachShader(program, fragment); gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error('shader link failed');
    buffer = gl.createBuffer();
    gl.useProgram(program); gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.clearColor(0, 0, 0, 0);
    return true;
  } catch {
    gl = null; program = null;
    return false;
  }
}

function project(x, y, z, angle) {
  const a = angle + yaw, c = Math.cos(a), s = Math.sin(a);
  const xx = x * c - y * s, yy = x * s + y * c;
  const tilt = 0.46 + pitch, depth = yy * Math.sin(tilt) + z;
  const scale = 1 / (1 + depth * 0.22);
  return [xx * scale, (yy * Math.cos(tilt) - z * 0.36) * scale];
}
function point(array, x, y, color, size = 1) {
  array.push(x*cameraZoom, y*cameraZoom, color[0],color[1],color[2],color[3]*cameraAlpha,size);
}
function octahedron(array, cx, cy, spin) {
  const r=config.nodeRadius, c=Math.cos(spin), s=Math.sin(spin);
  const vertices=[[0,-r,0],[0,r,0],[r,0,0],[0,0,r],[-r,0,0],[0,0,-r]];
  const rotate=([x,y,z])=>[x*c+z*s,y,-x*s+z*c];
  const v=vertices.map(rotate);
  const faces=[[0,2,3],[0,3,4],[0,4,5],[0,5,2],[1,3,2],[1,4,3],[1,5,4],[1,2,5]];
  faces.sort((a,b)=>a.reduce((sum,i)=>sum+v[i][2],0)-b.reduce((sum,i)=>sum+v[i][2],0));
  for (const face of faces) {
    const [a,b,d]=face.map(i=>v[i]);
    const ux=b[0]-a[0],uy=b[1]-a[1],uz=b[2]-a[2];
    const vx=d[0]-a[0],vy=d[1]-a[1],vz=d[2]-a[2];
    const nx=uy*vz-uz*vy,ny=uz*vx-ux*vz,nz=ux*vy-uy*vx;
    const light=Math.max(0,(nx*0.4-ny*0.7+nz*0.6)/(Math.hypot(nx,ny,nz)||1));
    const color=[0.48+0.30*light,0.23+0.25*light,0.10+0.16*light,0.95];
    for(const [x,y,z] of [a,b,d])point(array,cx+x+z*0.22,cy+y+z*0.34,color);
  }
}
function upload(values, primitive) {
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(values), gl.DYNAMIC_DRAW);
  for (const [name, width, offset] of [['p', 2, 0], ['c', 4, 8], ['s', 1, 24]]) {
    const loc = gl.getAttribLocation(program, name);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, width, gl.FLOAT, false, 28, offset);
  }
  gl.drawArrays(primitive, 0, values.length / 7);
}
function draw(now) {
  if (!stage?.isConnected || document.hidden || !wide.matches || !initialize()) return;
  const rect = stage.getBoundingClientRect();
  if (!rect.width || !rect.height || getComputedStyle(stage).display === 'none') return;
  canvas.hidden = false;
  Object.assign(canvas.style, {left:`${rect.left}px`, top:`${rect.top}px`, width:`${rect.width}px`, height:`${rect.height}px`});
  const dpr = Math.min(devicePixelRatio || 1, config.maxPixelRatio);
  const width = Math.round(rect.width * dpr), height = Math.round(rect.height * dpr);
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
  gl.viewport(0, 0, width, height); gl.clear(gl.COLOR_BUFFER_BIT);
  stage.classList.add('webgl-ready');
  const exitProgress=scene==='orbit' && stage.classList.contains('is-entering')
    ? Math.min(1,Math.max(0,(now-enteredAt)/config.enterMilliseconds)) : 0;
  cameraZoom=1+2.1*exitProgress*exitProgress;
  cameraAlpha=1-exitProgress;
  canvas.dataset.enterProgress=exitProgress.toFixed(2);
  canvas.dataset.yaw=yaw.toFixed(3);
  const intro = reduced.matches || !enabled ? 1 : Math.min(1, Math.max(0, (now - started) / config.introMilliseconds));
  const appear = 1 - (1 - intro) ** 3;
  if (scene === 'search') {
    const lines=[], dots=[];
    const count=Math.min(config.searchHitLimit, Math.max(1, Number(stage.dataset.hits) || 1));
    for(let i=0;i<count;i++) {
      const x=-0.25+1.1*(i+1)/(count+1),y=((i*7)%9-4)/5;
      point(lines,-0.88,0,[0.76,0.38,0.16,0.35]);
      point(lines,-0.88+(x+0.88)*appear,y*appear,[0.79,0.63,0.15,0.5]);
      point(dots,-0.88+(x+0.88)*appear,y*appear,[0.76,0.38,0.16,0.8],5*dpr);
    }
    point(dots,-0.88,0,[0.79,0.63,0.15,0.9],8*dpr);
    upload(lines,gl.LINES);upload(dots,gl.POINTS);return;
  }
  const inner = parseFloat(stage.style.getPropertyValue('--sl-a-in')) || 0;
  const outer = parseFloat(stage.style.getPropertyValue('--sl-a-out')) || 0;
  const computed = getComputedStyle(stage);
  const innerRadius = (parseFloat(computed.getPropertyValue('--sl-r-in')) || 155) * 2 / rect.width;
  const outerRadius = (parseFloat(computed.getPropertyValue('--sl-r-out')) || 270) * 2 / rect.width;
  const innerTilt = parseFloat(computed.getPropertyValue('--sl-k-in')) || 0.966;
  const outerTilt = parseFloat(computed.getPropertyValue('--sl-k-out')) || 0.866;
  const lines = [], dots = [], facets = [];
  const rings = [
    {r:outerRadius,z:0.40,a:outer,tilt:outerTilt,anchored:true,color:[0.76,0.38,0.16,0.52]},
    {r:0.65,z:0.00,a:inner,color:[0.79,0.63,0.15,0.39]},
    {r:innerRadius,z:-0.38,a:inner,tilt:innerTilt,anchored:true,color:[0.76,0.38,0.16,0.55]},
  ].slice(0, config.ringCount);
  const ringPoint=(ring,t,angle)=>ring.anchored
    ? [Math.sin(t+angle)*ring.r*appear, Math.cos(t+angle)*ring.r*ring.tilt*appear]
    : project(Math.cos(t)*ring.r*appear, Math.sin(t)*ring.r*appear, ring.z, angle);
  for (const ring of rings) {
    const angle = ring.a * Math.PI / 180;
    for (let i=0;i<config.ringSegments;i++) {
      for (const offset of [0,1]) {
        const t=(i+offset)/config.ringSegments*Math.PI*2;
        const [x,y]=ringPoint(ring,t,angle);
        point(lines,x,y,ring.color);
      }
    }
  }
  // The node counts mirror the four outer groups and six inner modules.
  for (const [ring,count] of [[rings[0],4],[rings[2],6]]) {
    for (let i=0;i<count;i++) {
      const t=i/count*Math.PI*2+(count===4?Math.PI/4:0);
      const [x,y]=ringPoint(ring,t,ring.a*Math.PI/180);
      octahedron(facets,x,y,ring.a*Math.PI/180+i*0.43);
    }
  }
  // Deterministic distribution keeps redraws stable and avoids a new particle system per route.
  for (let i=0;i<config.dustCount;i++) {
    const a=i*2.399963, r=0.22+0.72*((i*47)%config.dustCount)/config.dustCount;
    const [x,y]=project(Math.cos(a)*r,Math.sin(a)*r,((i%7)-3)*0.12,outer*Math.PI/360);
    point(dots,x,y,[0.79,0.63,0.15,0.3],(1+(i%3))*dpr);
  }
  upload(lines,gl.LINES); upload(facets,gl.TRIANGLES); upload(dots,gl.POINTS);
}
function tick(now) {
  raf = 0;
  if (!stage?.isConnected || document.hidden) return;
  if (now-lastPaint >= 1000/config.fps) { draw(now); lastPaint=now; }
  const entering=scene==='orbit' && stage.classList.contains('is-entering') && now-enteredAt < config.enterMilliseconds;
  const running = scene === 'search' ? now-started < config.introMilliseconds : stage.dataset.orbitSpeed !== 'stopped' || entering;
  if (enabled && !reduced.matches && wide.matches && running) {
    raf=requestAnimationFrame(tick);
  }
}
function schedule() {
  if (!stage?.isConnected || document.hidden || !wide.matches) return;
  if (!raf) raf=requestAnimationFrame(tick);
}
function prepareArtwork() {
  if (!config.seaBreeze.enabled || scene !== 'orbit') return;
  const artwork=stage.querySelector('.sea-breeze');
  if (!artwork) return;
  for (const name of ['base','hair','skirt','glow']) {
    const layer=artwork.querySelector(`.sea-breeze__${name}`), src=config.seaBreeze[name];
    if (!layer || !src || !src.startsWith('/static/shilie/assets/sea-breeze/')) continue;
    const image=new Image();
    image.onload=()=>{if(!artwork.isConnected)return;layer.dataset.assetState='loaded';layer.style.backgroundImage=`url("${src}")`;if(name==='base')artwork.querySelector('.sea-breeze__fallback').setAttribute('hidden','');};
    image.onerror=()=>{layer.dataset.assetState='unavailable';};
    image.src=src;
  }
  if (config.seaBreeze.video && config.seaBreeze.video.startsWith('/static/shilie/assets/sea-breeze/')) {
    const video=document.createElement('video');video.muted=true;video.loop=true;video.playsInline=true;
    video.setAttribute('aria-hidden','true');video.src=config.seaBreeze.video;
    video.addEventListener('error',()=>{video.dataset.playback='unavailable';video.hidden=true;artwork.querySelector('.sea-breeze__fallback').removeAttribute('hidden');});
    artwork.querySelector('.sea-breeze__base').append(video);
    if(enabled&&!reduced.matches)video.play().catch(()=>{video.dataset.playback='unavailable';});
  }
}
function refresh() {
  if (raf) cancelAnimationFrame(raf);
  raf=0;events?.abort();events=null;canvas.hidden=true;canvas.classList.remove('is-entering');enteredAt=0;
  stage=document.querySelector('.sl-orbit') || document.querySelector('.search-space');
  scene=stage?.classList.contains('search-space') ? 'search' : 'orbit';
  if (!stage || !wide.matches) return;
  if (scene === 'orbit') prepareArtwork();
  if (!initialize()) return;
  if (scene === 'search') { started=performance.now();lastPaint=0;schedule();return; }
  events=new AbortController(); const options={signal:events.signal};
  // The existing orbit intentionally has pointer-events:none; its container receives drags.
  const surface=stage.closest('.home-orbit-wrap') || stage;
  surface.addEventListener('pointerdown', e=>{
    if (e.target.closest('a,button')) return;
    const rect=stage.getBoundingClientRect();
    if(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)return;
    dragging=true;lastX=e.clientX;lastY=e.clientY;surface.setPointerCapture(e.pointerId);
  },options);
  surface.addEventListener('pointerup',()=>{dragging=false;},options);
  surface.addEventListener('pointercancel',()=>{dragging=false;},options);
  surface.addEventListener('pointermove',e=>{
    if (dragging && enabled && !reduced.matches) {
      yaw+=(e.clientX-lastX)*config.dragSensitivity;
      pitch=Math.max(-0.25,Math.min(0.25,pitch+(e.clientY-lastY)*config.dragSensitivity));
      lastX=e.clientX;lastY=e.clientY;schedule();
    }
  },options);
  for (const name of ['pointerenter','pointerleave','focusin','focusout']) stage.addEventListener(name,()=>setTimeout(schedule,0),options);
  started=performance.now();lastPaint=0;schedule();
}
canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();if(raf)cancelAnimationFrame(raf);raf=0;stage?.classList.remove('webgl-ready');canvas.hidden=true;});
canvas.addEventListener('webglcontextrestored',()=>{gl=null;program=null;attempted=false;refresh();});
document.addEventListener('visibilitychange',()=>{if(document.hidden){if(raf)cancelAnimationFrame(raf);raf=0;}else schedule();});
window.addEventListener('resize',refresh,{passive:true});
window.addEventListener('scroll',schedule,{passive:true});
window.addEventListener('shilie:entering-workspace',()=>{enteredAt=performance.now();canvas.classList.add('is-entering');schedule();});
reduced.addEventListener('change',()=>{syncToggle();schedule();});
export function refreshTemporalCanvas() { refresh(); }
