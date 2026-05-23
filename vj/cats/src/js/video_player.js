// VideoPlayer — overlays a native <video> on top of the p5 canvas.
//
// Two playback modes:
//   pingPong: true  (default) — forward 0..n → reverse n..0 → repeat.
//     Uses two <video> elements (original + pre-encoded reversed copy via
//     ffmpeg `-vf reverse`, named `<src>_rev.mp4`). Both play forward
//     natively so frames are frame-accurate (no rAF seeking).
//   pingPong: false — single-shot forward play only. Stops at the last
//     frame (deck advances away before it sits long).
//
// Both modes are pre-buffered at startup so the deck transition is instant.
export function createVideoPlayer(src, opts = {}) {
  const pingPong = opts.pingPong !== false;

  function makeEl(source) {
    const v = document.createElement('video');
    v.src         = source;
    v.preload     = 'auto';
    v.loop        = false;
    v.muted       = true;
    v.playsInline = true;
    Object.assign(v.style, {
      position:        'fixed',
      top:             '50%',
      left:            '50%',
      transform:       'translate(-50%, -50%)',
      zIndex:          '2',
      display:         'none',
      objectFit:       'cover',
      backgroundColor: '#000',
      width:           '0px',
      height:          '0px',
    });
    document.body.appendChild(v);
    v.load();
    return v;
  }

  const elFwd = makeEl(src);
  const elRev = pingPong ? makeEl(src.replace(/\.mp4$/i, '_rev.mp4')) : null;

  let active   = false;
  let rotation = 0;
  let curW     = 0;
  let curH     = 0;
  let leg      = 'fwd';   // 'fwd' or 'rev' — which element is currently showing

  function applyTransformTo(v) {
    if (!v) return;
    v.style.transform = `translate(-50%, -50%) rotate(${rotation}deg)`;
  }

  function showEl(v) {
    v.style.width   = curW + 'px';
    v.style.height  = curH + 'px';
    v.style.display = 'block';
    applyTransformTo(v);
  }

  function hideEl(v) {
    if (!v) return;
    v.style.display = 'none';
  }

  // ── Leg switch (only in ping-pong mode) ─────────────────────────────────
  function onForwardEnded() {
    if (!active || !pingPong) return;
    leg = 'rev';
    elFwd.pause();
    hideEl(elFwd);
    elRev.currentTime = 0;
    showEl(elRev);
    elRev.play().catch(() => {});
  }

  function onReverseEnded() {
    if (!active || !pingPong) return;
    leg = 'fwd';
    elRev.pause();
    hideEl(elRev);
    elFwd.currentTime = 0;
    showEl(elFwd);
    elFwd.play().catch(() => {});
  }

  elFwd.addEventListener('ended', onForwardEnded);
  elFwd.addEventListener('timeupdate', () => {
    if (!active || !pingPong || leg !== 'fwd') return;
    if (elFwd.duration && elFwd.currentTime >= elFwd.duration - 0.05) {
      onForwardEnded();
    }
  });
  if (elRev) {
    elRev.addEventListener('ended', onReverseEnded);
    elRev.addEventListener('timeupdate', () => {
      if (!active || !pingPong || leg !== 'rev') return;
      if (elRev.duration && elRev.currentTime >= elRev.duration - 0.05) {
        onReverseEnded();
      }
    });
  }

  function show(w, h) {
    curW   = w;
    curH   = h;
    active = true;
    leg    = 'fwd';
    if (elRev) {
      hideEl(elRev);
      elRev.pause();
      elRev.currentTime = 0;
    }
    elFwd.currentTime = 0;
    showEl(elFwd);
    elFwd.play().catch(() => {});
  }

  function hide() {
    active = false;
    elFwd.pause();
    elFwd.currentTime = 0;
    hideEl(elFwd);
    if (elRev) {
      elRev.pause();
      elRev.currentTime = 0;
      hideEl(elRev);
    }
    leg = 'fwd';
  }

  function resize(w, h) {
    curW = w;
    curH = h;
    if (active) {
      const cur = leg === 'fwd' ? elFwd : elRev;
      cur.style.width  = w + 'px';
      cur.style.height = h + 'px';
    }
  }

  function setRotation(deg) {
    rotation = deg;
    applyTransformTo(elFwd);
    if (elRev) applyTransformTo(elRev);
  }

  function tryPlay() {
    if (!active) return;
    const cur = leg === 'fwd' ? elFwd : elRev;
    if (cur) cur.play().catch(() => {});
  }

  return { show, hide, resize, setRotation, tryPlay, get active() { return active; } };
}
