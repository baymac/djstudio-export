'use strict';

const BAR_H = 22;

let cachedPending = null; // { ytId, tracks, title, tlUrl }
let pipWin        = null;
let tickInterval  = null;
let origParent    = null;
let origSibling   = null;

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(s) {
  s = Math.floor(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
    : `${m}:${String(sec).padStart(2, '0')}`;
}

function parseTime(str) {
  if (!str || str === '?') return null;
  const p = str.split(':').map(Number);
  if (p.length === 2) return p[0] * 60 + p[1];
  if (p.length === 3) return p[0] * 3600 + p[1] * 60 + p[2];
  return null;
}

function renderTracklist(doc, tracks) {
  const tlist = doc.getElementById('tlist');
  if (!tlist) return;
  const tscroll = doc.createElement('div'); tscroll.id = 'tscroll';
  const table   = doc.createElement('table');
  const thead   = doc.createElement('thead');
  const hrow    = doc.createElement('tr');
  [['#', 'tn'], ['Time', 'tt'], ['Artist', 'ta'], ['Track', 'tk']].forEach(([txt, cls]) => {
    const th = doc.createElement('th'); th.className = cls; th.textContent = txt;
    hrow.appendChild(th);
  });
  thead.appendChild(hrow);
  table.appendChild(thead);
  const tbody = doc.createElement('tbody');
  let n = 0;
  tracks.forEach((t) => {
    if (!t.w) n++;
    const tr = doc.createElement('tr');
    if (t.w) tr.className = 'tw';
    const tdN = doc.createElement('td'); tdN.className = 'tn'; tdN.textContent = t.w ? '' : String(n);
    const tdT = doc.createElement('td'); tdT.className = 'tt'; tdT.textContent = t.time || '';
    const tdA = doc.createElement('td'); tdA.className = 'ta';
    if (t.w) { const wp = doc.createElement('i'); wp.className = 'wp'; wp.textContent = 'w/ '; tdA.appendChild(wp); }
    tdA.appendChild(doc.createTextNode(t.artist));
    const tdK = doc.createElement('td'); tdK.className = 'tk'; tdK.textContent = t.track;
    tr.appendChild(tdN); tr.appendChild(tdT); tr.appendChild(tdA); tr.appendChild(tdK);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  tscroll.appendChild(table);
  tlist.appendChild(tscroll);
}

// ── Document PiP ─────────────────────────────────────────────────────────────
async function enterPiP() {
  if (pipWin && !pipWin.closed) { pipWin.focus(); return; }
  if (!cachedPending) throw new Error('No tracklist data for this video');

  const video = document.querySelector('video.html5-main-video') || document.querySelector('video');
  if (!video) throw new Error('Video not ready — try again in a moment');

  const { tracks, title, tlUrl } = cachedPending;
  // diagnostic: log what we actually received before rendering
  const wArtists = tracks.filter(t => t.w).slice(0, 8).map(t => t.artist);
  console.log('[yt-tl-pip] enterPiP got ' + tracks.length + ' tracks, w/ artists:');
  console.log(JSON.stringify(wArtists, null, 2));
  const parsedTimes = tracks.map((t) => parseTime(t.time));

  origParent  = video.parentNode;
  origSibling = video.nextSibling;

  // requestWindow() must be the first await — user activation transfers here
  pipWin = await window.documentPictureInPicture.requestWindow({ width: 340, height: 580 });

  const style = pipWin.document.createElement('style');
  style.textContent = `
    * { margin:0; padding:0; box-sizing:border-box; }
    html,body { width:100%; height:100%; background:#000; overflow:hidden;
                font-family:system-ui,sans-serif; display:flex; flex-direction:column; }
    #hdr  { flex:0 0 auto; display:flex; align-items:center; gap:1.5vw;
            padding:.6vw 2.2vw; background:#0a0a0a; border-bottom:1px solid #1a1a1a; }
    #httl { flex:1 1 0; min-width:0; color:#666; font-size:2.5vw;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    #hlnk { flex:0 0 auto; color:#c02020; font-size:3.2vw; text-decoration:none; line-height:1; }
    #hlnk:hover { color:#e03030; }
    #vwrap { flex:1 1 0; min-height:0; overflow:hidden; }
    video  { width:100%!important; height:100%!important; object-fit:contain!important; display:block!important; }
    #bar   { flex:0 0 ${BAR_H}px; background:rgba(0,0,0,.9);
             display:flex; flex-direction:column; justify-content:center; gap:3px; padding:0 2.2vw; }
    #track { height:2px; background:rgba(255,255,255,.2); border-radius:2px; cursor:pointer; flex-shrink:0; }
    #fill  { height:100%; background:#c02020; border-radius:2px; transform-origin:left; will-change:transform; }
    #time  { color:#888; font-size:2.8vw; line-height:1; }
    #tlist   { flex:0 0 60%; background:#0c0c0c; border-top:1px solid #222;
               overflow:hidden; display:flex; flex-direction:column; }
    #tscroll { flex:1 1 0; min-height:0; overflow-y:auto; overflow-x:hidden;
               scrollbar-width:thin; scrollbar-color:#2a2a2a transparent; }
    table    { width:100%; border-collapse:collapse; font-size:2.8vw; table-layout:fixed; }
    thead th { position:sticky; top:0; background:#0f0f0f; color:#555; font-weight:600;
               font-size:2.3vw; text-transform:uppercase; letter-spacing:.05em;
               text-align:left; padding:.9vw 1.5vw .6vw; border-bottom:1px solid #1a1a1a; }
    td       { padding:.55vw 1.5vw; vertical-align:top; line-height:1.4;
               overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .ta, .tk { white-space:normal; }
    tr:hover td  { background:rgba(255,255,255,.05); }
    tr.active td { background:rgba(192,32,32,.12); }
    .tn { color:#333; width:7vw; font-size:2.4vw; }
    .tt { color:#c02020; width:16vw; font-variant-numeric:tabular-nums; }
    .ta { color:#999; width:32%; }
    .tk { color:#ddd; }
    tr.tw td  { opacity:.65; }
    tr.tw .ta { color:#666; }
    i.wp { font-style:italic; color:#555; margin-right:.6vw; }
  `;
  pipWin.document.head.appendChild(style);

  const hdr  = pipWin.document.createElement('div');  hdr.id  = 'hdr';
  const httl = pipWin.document.createElement('span'); httl.id = 'httl'; httl.textContent = title;
  const hlnk = pipWin.document.createElement('a');    hlnk.id = 'hlnk';
  hlnk.href = tlUrl; hlnk.target = '_blank'; hlnk.textContent = '↗';
  hdr.appendChild(httl); hdr.appendChild(hlnk);

  const vwrap = pipWin.document.createElement('div'); vwrap.id = 'vwrap';
  const bar   = pipWin.document.createElement('div'); bar.id   = 'bar';
  const track = pipWin.document.createElement('div'); track.id = 'track';
  const fill  = pipWin.document.createElement('div'); fill.id  = 'fill';
  const time  = pipWin.document.createElement('div'); time.id  = 'time';
  const tlist = pipWin.document.createElement('div'); tlist.id = 'tlist';

  track.appendChild(fill);
  bar.appendChild(track); bar.appendChild(time);
  pipWin.document.body.appendChild(hdr);
  pipWin.document.body.appendChild(vwrap);
  pipWin.document.body.appendChild(bar);
  pipWin.document.body.appendChild(tlist);
  vwrap.appendChild(video);

  track.addEventListener('click', (e) => {
    if (!video.duration) return;
    video.currentTime = (e.offsetX / track.offsetWidth) * video.duration;
  });

  tickInterval = setInterval(() => {
    if (!video.duration || !pipWin || pipWin.closed) return;
    fill.style.transform = `scaleX(${video.currentTime / video.duration})`;
    time.textContent     = `${fmt(video.currentTime)} / ${fmt(video.duration)}`;

    let idx = -1;
    for (let i = parsedTimes.length - 1; i >= 0; i--) {
      if (parsedTimes[i] !== null && video.currentTime >= parsedTimes[i]) { idx = i; break; }
    }
    pipWin.document.querySelectorAll('#tscroll tbody tr').forEach((tr, i) =>
      tr.classList.toggle('active', i === idx)
    );
  }, 500);

  pipWin.addEventListener('pagehide', () => {
    clearInterval(tickInterval); tickInterval = null;
    origParent?.insertBefore(video, origSibling);
    pipWin = null;
    showFab();
  });

  renderTracklist(pipWin.document, tracks);
  console.log('[yt-tl-pip] PiP open —', tracks.length, 'tracks');
}

// ── FAB ───────────────────────────────────────────────────────────────────────
function showFab() {
  if (document.getElementById('ytTlPipFab')) return;
  if (pipWin && !pipWin.closed) return;

  const fab = document.createElement('button');
  fab.id = 'ytTlPipFab';
  fab.textContent = '▶ Open PiP + Tracklist';
  fab.style.cssText = [
    'position:fixed', 'top:24px', 'right:24px', 'z-index:2147483647',
    'background:#c02020', 'color:#fff', 'border:none',
    'padding:10px 18px', 'border-radius:6px',
    'font:600 13px/1 system-ui,sans-serif',
    'cursor:pointer', 'box-shadow:0 2px 10px rgba(0,0,0,.6)',
    'transition:background .15s',
  ].join(';');
  fab.onmouseenter = () => { if (!fab.disabled) fab.style.background = '#e03030'; };
  fab.onmouseleave = () => { if (!fab.disabled) fab.style.background = '#c02020'; };

  fab.addEventListener('click', async () => {
    fab.textContent = 'Opening…';
    fab.disabled = true;
    try {
      await enterPiP();
    } catch (err) {
      console.error('[yt-tl-pip]', err);
      fab.textContent = '▶ Open PiP + Tracklist';
      fab.disabled = false;
      return;
    }
    fab.remove();
  });

  // Append to <html> — survives YouTube's SPA DOM management
  document.documentElement.appendChild(fab);
  console.log('[yt-tl-pip] FAB injected');

  // Re-inject if evicted (max 5 retries, auto-stop after 5s of stability)
  let retries = 0;
  const observer = new MutationObserver(() => {
    if (document.getElementById('ytTlPipFab')) return;
    observer.disconnect();
    if (++retries <= 5 && cachedPending && (!pipWin || pipWin.closed)) {
      setTimeout(showFab, 800);
    }
  });
  observer.observe(document.documentElement, { childList: true });
  setTimeout(() => observer.disconnect(), 5000);
}

// ── Keyboard shortcut entry point ─────────────────────────────────────────────
window.__ytTlPip = { enter: enterPiP };

// ── Wait for YouTube's player to mount ────────────────────────────────────────
function waitForPlayer(fn, attempts) {
  attempts = attempts || 0;
  if (document.querySelector('ytd-app') || document.querySelector('video')) {
    fn();
  } else if (attempts < 30) {
    setTimeout(() => waitForPlayer(fn, attempts + 1), 300);
  }
}

// ── Boot path 1: check storage at document_idle ───────────────────────────────
(async () => {
  const ytId = new URL(location.href).searchParams.get('v');
  if (!ytId) return;
  try {
    const data = await chrome.storage.session.get('pending_pip');
    if (!data.pending_pip || data.pending_pip.ytId !== ytId) return;
    cachedPending = data.pending_pip;
    waitForPlayer(showFab);
  } catch {
    // storage unavailable — SHOW_PIP_FAB message is the fallback
  }
})();

// ── Boot path 2: background sends SHOW_PIP_FAB ────────────────────────────────
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== 'SHOW_PIP_FAB') return;

  if (cachedPending) { waitForPlayer(showFab); return; }

  const pip = msg.pending_pip;
  if (!pip) return;

  const ytId = new URL(location.href).searchParams.get('v');
  if (pip.ytId !== ytId) return;

  cachedPending = pip;
  waitForPlayer(showFab);
});
