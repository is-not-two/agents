/* 时列 · 动态壁纸接口（wallpaper adapter）
 * ---------------------------------------------------------------
 * 职责：把「用户提供的动态素材」接进首页，并在素材缺失时提供持续运行的程序化动态层。
 * 零依赖、同源、无构建链；可直接放进 /static/shilie/ 使用。
 *
 * 一行接入（在引入本脚本之前或之后均可）：
 *   ShilieWallpaper.mount(document.getElementById('wallpaper'));
 *   ShilieWallpaper.configure({ video: 'assets/wallpaper/sea-breeze.mp4' });
 *
 * 配置字段（configure(options)）：
 *   image      静态帧，必需路径；视频/动图加载失败时显示它。缺省则用纯 CSS 渐变底。
 *   video      可选循环视频（.mp4 / .webm），优先级最高，静音 loop playsinline。
 *   animated   可选动图（.apng / .gif / .webp），优先级次之。
 *   frames     可选序列帧 { pattern, count, fps, pad }，pattern 用 {i} 占位，如
 *              { pattern:'assets/wallpaper/frame-{i}.webp', count:120, fps:24, pad:3 }
 *   poster     视频封面图路径。
 *   loopSeconds 循环时长提示（默认 6），用于程序化层的动画周期同步。
 *
 * 素材路径白名单（违反则拒绝并 emit error，不发任何请求）：
 *   本地预览：assets/wallpaper/xxx
 *   线上：   /static/shilie/assets/wallpaper/xxx
 *   必须同源、无 query / hash / 协议相对 URL、不含 .. 、扩展名在白名单内。
 *
 * 优先级：video > animated > frames > procedural(静态帧 + 程序化动态层) > still(纯底)
 * 任何一级失败自动落到下一级；从未出现空白或外链请求。
 *
 * 状态机：idle → probing → video | animated | frames | procedural | still
 *   getState() 返回 { mode, source, image, video, animated, frames, paused, reason }
 *
 * 事件：on('statechange', fn) / on('error', fn) / on('ready', fn)；off(name, fn)
 *   ready 在每次成功切换模式后触发一次。
 *
 * 运行控制：pause() / resume() / destroy() / refresh()
 *   自动响应：prefers-reduced-motion、shilie:motionchange（关闭动效开关）、
 *   visibilitychange（页面隐藏停播放）、homeRoute 离开首页（由页面调用 pause）。
 *   reduced-motion 或关闭动效时：停用视频/序列帧/程序化动画，只保留静态帧。
 * --------------------------------------------------------------- */

(function (global) {
  'use strict';

  var PREFIXES = ['/static/shilie/assets/wallpaper/', 'assets/wallpaper/'];
  var VIDEO_EXT = ['.mp4', '.webm'];
  var ANIM_EXT = ['.apng', '.gif', '.webp'];
  var IMAGE_EXT = ['.webp', '.png', '.jpg', '.jpeg', '.avif', '.gif', '.apng'];
  var FRAME_EXT = ['.webp', '.png', '.jpg', '.jpeg', '.avif'];

  var listeners = {};
  var explicit = {};
  var root = null;
  var els = {};
  var reduced = global.matchMedia('(prefers-reduced-motion: reduce)');
  var frameTimer = 0;
  var frameIndex = 0;
  var frameImages = [];
  var generation = 0;

  var config = {
    image: '',
    video: '',
    animated: '',
    frames: null,
    poster: '',
    loopSeconds: 6
  };

  var state = {
    mode: 'idle',
    source: '',
    paused: false,
    reason: ''
  };

  function emit(name, payload) {
    (listeners[name] || []).slice().forEach(function (fn) {
      try { fn(payload); } catch (e) { /* 监听器异常不影响壁纸 */ }
    });
  }
  function setState(mode, source, reason) {
    var changed = state.mode !== mode || state.source !== source;
    state.mode = mode;
    state.source = source || '';
    state.reason = reason || '';
    if (root) root.dataset.wpMode = mode;
    if (changed) {
      emit('statechange', getState());
      emit('ready', getState());
    }
  }
  function getState() {
    return {
      mode: state.mode,
      source: state.source,
      paused: state.paused,
      reason: state.reason,
      image: config.image,
      video: config.video,
      animated: config.animated,
      frames: config.frames,
      loopSeconds: config.loopSeconds
    };
  }

  /* 同源 + 目录 + 扩展名三重白名单；任何不合规路径返回空字符串 */
  function safePath(value, extensions) {
    if (typeof value !== 'string' || !value) return '';
    var url;
    try { url = new URL(value, global.location.origin); } catch (e) { return ''; }
    if (url.origin !== global.location.origin) return '';
    if (url.search || url.hash) return '';
    if (value.indexOf('//') === 0 || value.indexOf('..') !== -1) return '';
    var ok = PREFIXES.some(function (p) { return url.pathname.indexOf(p) !== -1 || value.indexOf(p) === 0; });
    if (!ok) return '';
    var lower = url.pathname.toLowerCase();
    if (!extensions.some(function (ext) { return lower.endsWith(ext); })) return '';
    return value;
  }

  /* 自动发现：读取 assets/wallpaper/manifest.json（可选）。
     浏览器不能列目录，所以「放进素材就自动接管」需要一个同源清单文件；
     不存在时静默跳过，不发错误，也不覆盖显式 configure 的值。 */
  function loadManifest() {
    var path = 'assets/wallpaper/manifest.json';
    var url;
    try { url = new URL(path, global.location.origin); } catch (e) { return Promise.resolve(false); }
    if (url.origin !== global.location.origin) return Promise.resolve(false);
    return fetch(path, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : false; })
      .then(function (data) {
        if (!data || typeof data !== 'object') return false;
        [['image', IMAGE_EXT], ['poster', IMAGE_EXT], ['video', VIDEO_EXT], ['animated', ANIM_EXT]].forEach(function (pair) {
          var k = pair[0];
          if (explicit[k] || typeof data[k] !== 'string' || !data[k]) return;
          var ok = safePath(data[k], pair[1]);
          if (ok) config[k] = ok;
          else emit('error', { kind: 'manifest', detail: '字段路径不合规: ' + k });
        });
        if (!explicit.frames && data.frames && typeof data.frames.pattern === 'string') {
          if (safePath(data.frames.pattern.replace('{i}', '0'), FRAME_EXT)) config.frames = data.frames;
        }
        if (typeof data.loopSeconds === 'number' && !explicit.loopSeconds) config.loopSeconds = data.loopSeconds;
        return true;
      })
      .catch(function () { return false; });
  }

  function motionOff() {
    return reduced.matches || document.documentElement.dataset.motion === 'off';
  }

  function probeImage(url) {
    return new Promise(function (resolve) {
      if (!url) { resolve(false); return; }
      var img = new Image();
      var done = false;
      var timer = setTimeout(function () { if (!done) { done = true; resolve(false); } }, 10000);
      img.onload = function () { if (!done) { done = true; clearTimeout(timer); resolve(true); } };
      img.onerror = function () { if (!done) { done = true; clearTimeout(timer); resolve(false); } };
      img.src = url;
    });
  }
  function probeVideo(url) {
    return new Promise(function (resolve) {
      if (!url) { resolve(false); return; }
      var v = document.createElement('video');
      var done = false;
      var timer = setTimeout(function () { if (!done) { done = true; resolve(false); } }, 4000);
      v.preload = 'metadata';
      v.muted = true;
      v.onloadeddata = function () { if (!done) { done = true; clearTimeout(timer); resolve(true); } };
      v.onerror = function () { if (!done) { done = true; clearTimeout(timer); resolve(false); } };
      v.src = url;
    });
  }

  function clearLayers() {
    if (frameTimer) { clearInterval(frameTimer); frameTimer = 0; }
    frameImages = [];
    frameIndex = 0;
    if (!root) return;
    if (els.video) { els.video.pause(); els.video.removeAttribute('src'); els.video.hidden = true; }
    if (els.still) els.still.hidden = true;
    if (els.procedural) els.procedural.hidden = true;
  }

  function showStill(url) {
    if (!els.still) return;
    if (url) { els.still.src = url; els.still.hidden = false; }
    else { els.still.removeAttribute('src'); els.still.hidden = true; }
  }
  function showProcedural(on) {
    if (els.procedural) els.procedural.hidden = !on || motionOff();
  }
  function startFrames(spec) {
    var pattern = spec.pattern, count = Number(spec.count) || 0;
    var fps = Math.max(1, Math.min(60, Number(spec.fps) || 24));
    var pad = Number(spec.pad) || 0;
    var urls = [];
    for (var i = 0; i < count; i++) {
      var token = pad ? String(i).padStart(pad, '0') : String(i);
      var raw = pattern.replace('{i}', token);
      var ok = safePath(raw, FRAME_EXT);
      if (!ok) { emit('error', { kind: 'frames', detail: '帧路径不合规: ' + raw }); return false; }
      urls.push(ok);
    }
    if (!urls.length) return false;
    frameImages = urls.map(function (u) { var im = new Image(); im.src = u; return im; });
    showStill(urls[0]);
    frameTimer = setInterval(function () {
      if (state.paused || document.hidden || motionOff()) return;
      frameIndex = (frameIndex + 1) % frameImages.length;
      if (els.still) els.still.src = frameImages[frameIndex].src;
    }, Math.round(1000 / fps));
    return true;
  }

  async function refresh() {
    var ticket = ++generation;
    if (!root) return;
    clearLayers();
    setState('probing', '', '检测本地素材');

    var image = safePath(config.image, IMAGE_EXT);
    var poster = safePath(config.poster, IMAGE_EXT);
    var video = safePath(config.video, VIDEO_EXT);
    var animated = safePath(config.animated, ANIM_EXT);
    var spec = config.frames;

    if (poster && els.video) els.video.poster = poster;
    if (root) root.style.setProperty('--wp-loop', (config.loopSeconds || 6) + 's');

    /* 静态帧乐观显示：先让首屏立刻有画面，再后台校验。
       大体积素材在公网上可能比探测超时更慢，阻塞式探测会误判为「素材缺失」。 */
    var imageReady = Boolean(image);
    if (image) {
      probeImage(image).then(function (ok) {
        if (!ok && ticket === generation) {
          emit('error', { kind: 'image', detail: '静态帧不可用，已隐藏' });
          if (els.still) { els.still.removeAttribute('src'); els.still.hidden = true; }
        }
      });
    }
    if (ticket !== generation) return;

    if (motionOff()) {
      showStill(imageReady ? image : '');
      setState(imageReady ? 'still' : 'procedural', imageReady ? image : '', '按动效偏好停用动态层');
      showProcedural(!imageReady);
      return;
    }

    if (video && await probeVideo(video)) {
      if (ticket !== generation) return;
      showStill(imageReady ? image : '');
      if (els.video) {
        els.video.src = video;
        els.video.hidden = false;
        var p = els.video.play();
        if (p && p.catch) p.catch(function () {
          config.video = '';
          emit('error', { kind: 'video', detail: '自动播放被拦截，切换下一级' });
          refresh();
        });
      }
      showProcedural(true);
      setState('video', video, '同源循环视频');
      return;
    }
    if (ticket !== generation) return;

    if (animated && await probeImage(animated)) {
      if (ticket !== generation) return;
      showStill(animated);
      showProcedural(true);
      setState('animated', animated, '同源动图');
      return;
    }
    if (ticket !== generation) return;

    if (spec && spec.pattern && startFrames(spec)) {
      showProcedural(true);
      setState('frames', spec.pattern, '同源序列帧');
      return;
    }

    showStill(imageReady ? image : '');
    showProcedural(true);
    setState('procedural', imageReady ? image : '', '素材未接入，运行程序化动态层');
  }

  function pause() {
    state.paused = true;
    if (els.video) els.video.pause();
    if (frameTimer) { clearInterval(frameTimer); frameTimer = 0; }
  }
  function resume() {
    state.paused = false;
    if (els.video && state.mode === 'video' && !motionOff() && !document.hidden) {
      var p = els.video.play();
      if (p && p.catch) p.catch(function () {});
    }
    if (state.mode === 'frames' && config.frames && !frameTimer) startFrames(config.frames);
  }

  function mount(node) {
    root = node;
    if (!root) { emit('error', { kind: 'mount', detail: '容器不存在' }); return api; }
    els.still = root.querySelector('[data-wp-still]');
    els.video = root.querySelector('[data-wp-video]');
    els.procedural = root.querySelector('[data-wp-procedural]');
    if (els.video) {
      els.video.muted = true;
      els.video.loop = true;
      els.video.playsInline = true;
      els.video.setAttribute('muted', '');
      els.video.setAttribute('playsinline', '');
      els.video.addEventListener('error', function () {
        if (!els.video.getAttribute('src')) return;
        emit('error', { kind: 'video', detail: '播放失败，回退下一级' });
        config.video = '';
        refresh();
      });
    }
    reduced.addEventListener('change', refresh);
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) pause(); else resume();
    });
    document.addEventListener('shilie:motionchange', refresh);
    loadManifest().then(function () { refresh(); });
    return api;
  }

  var api = {
    mount: mount,
    configure: function (options) {
      if (!options || typeof options !== 'object') return api;
      Object.keys(config).forEach(function (k) {
        if (Object.prototype.hasOwnProperty.call(options, k)) {
          config[k] = options[k];
          var v = options[k];
          if (v !== '' && v !== null && v !== undefined) explicit[k] = true;
        }
      });
      refresh();
      return api;
    },
    refresh: refresh,
    pause: pause,
    resume: resume,
    getState: getState,
    on: function (name, fn) {
      (listeners[name] = listeners[name] || []).push(fn);
      return api;
    },
    off: function (name, fn) {
      listeners[name] = (listeners[name] || []).filter(function (f) { return f !== fn; });
      return api;
    },
    destroy: function () {
      generation++;
      clearLayers();
      listeners = {};
      root = null;
      state.mode = 'idle';
    }
  };

  global.ShilieWallpaper = api;
  if (global.SHILIE_WALLPAPER_SOURCE) api.configure(global.SHILIE_WALLPAPER_SOURCE);
})(window);
