'use strict';

let cachedPending = null;
let pipWin        = null;
let tickInterval  = null;
let origParent    = null;
let origSibling   = null;

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

const PLAY_SVG  = `<svg viewBox="0 0 24 24" width="9vw" height="9vw" fill="white"><polygon points="6,3 20,12 6,21"/></svg>`;
const PAUSE_SVG = `<svg viewBox="0 0 24 24" width="9vw" height="9vw" fill="white"><rect x="5" y="3" width="4" height="18" rx="1"/><rect x="15" y="3" width="4" height="18" rx="1"/></svg>`;

// ── Document PiP ─────────────────────────────────────────────────────────────
async function enterPiP() {
  if (pipWin && !pipWin.closed) { pipWin.focus(); return; }
  if (!cachedPending) throw new Error('No tracklist data for this video');

  const video = document.querySelector('video.html5-main-video') || document.querySelector('video');
  if (!video) throw new Error('Video not ready — try again in a moment');

  const { ytId, tracks, title, tlUrl } = cachedPending;
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

    /* ── Video + overlay ── */
    #vwrap { flex:1 1 0; min-height:0; position:relative; overflow:hidden; background:#000; }
    video  { width:100%!important; height:100%!important;
             object-fit:contain!important; display:block!important; }

    #overlay { position:absolute; inset:0; display:flex; flex-direction:column;
               opacity:0; transition:opacity .22s; pointer-events:none; }
    #vwrap:hover #overlay { opacity:1; pointer-events:auto; }

    /* center controls row */
    #ctrl-mid { flex:1 1 0; display:flex; align-items:center; justify-content:center; gap:5.5vw; }
    .ctl { background:none; border:none; color:#fff; cursor:pointer; padding:1.2vw;
           filter:drop-shadow(0 1px 4px rgba(0,0,0,.95));
           transition:transform .12s; }
    .ctl:hover { transform:scale(1.15); }

    /* seek icon: circular arrow + "10" label inside */
    .ctl-seek { position:relative; display:inline-flex; align-items:center; justify-content:center; }
    .ctl-seek svg { display:block; }
    .ctl-n { position:absolute; font-size:2.6vw; font-weight:700;
             font-family:system-ui,sans-serif; line-height:1;
             top:52%; left:50%; transform:translate(-50%,-50%); pointer-events:none; }

    /* bottom controls row */
    #ctrl-bot { flex:0 0 auto; padding:0 3vw 3vw;
                background:linear-gradient(to top, rgba(0,0,0,.75) 0%, transparent 100%);
                display:flex; flex-direction:column; gap:2vw; }
    #time { color:#d0d0d0; font-size:2.8vw; line-height:1; font-variant-numeric:tabular-nums; }

    /* range slider */
    #track { -webkit-appearance:none; appearance:none; width:100%; height:4px;
             border-radius:2px; outline:none; cursor:pointer; flex-shrink:0;
             background:linear-gradient(to right,
               #ff0000 0%, #ff0000 var(--pct,0%),
               rgba(255,255,255,.3) var(--pct,0%), rgba(255,255,255,.3) 100%); }
    #track::-webkit-slider-thumb {
      -webkit-appearance:none; width:13px; height:13px; border-radius:50%;
      background:#fff; cursor:pointer; box-shadow:0 0 4px rgba(0,0,0,.7); }
    #track:hover { height:5px; }
    #track:hover::-webkit-slider-thumb { width:15px; height:15px; }

    /* ── Tracklist ── */
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
    tr.active td { background:rgba(255,0,0,.12); }
    .tn { color:#333; width:7vw; font-size:2.4vw; }
    .tt { color:#ff0000; width:16vw; font-variant-numeric:tabular-nums; }
    .ta { color:#999; width:32%; }
    .tk { color:#ddd; }
    tr.tw td  { opacity:.65; }
    tr.tw .ta { color:#666; }
    i.wp { font-style:italic; color:#555; margin-right:.6vw; }
  `;
  pipWin.document.head.appendChild(style);

  // ── Video + overlay ──────────────────────────────────────────────────────
  const vwrap   = pipWin.document.createElement('div'); vwrap.id = 'vwrap';
  const overlay = pipWin.document.createElement('div'); overlay.id = 'overlay';

  const ctrlMid = pipWin.document.createElement('div'); ctrlMid.id = 'ctrl-mid';
  const ctrlBot = pipWin.document.createElement('div'); ctrlBot.id = 'ctrl-bot';

  const btnBack = pipWin.document.createElement('button');
  btnBack.className = 'ctl'; btnBack.title = 'Back 10s';
  btnBack.innerHTML = `
    <span class="ctl-seek">
      <svg viewBox="0 0 24 24" width="7vw" height="7vw" fill="white">
        <path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4
                 c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/>
      </svg>
      <span class="ctl-n">10</span>
    </span>`;

  const btnPlay = pipWin.document.createElement('button');
  btnPlay.className = 'ctl'; btnPlay.id = 'btn-play';

  const btnFwd = pipWin.document.createElement('button');
  btnFwd.className = 'ctl'; btnFwd.title = 'Forward 10s';
  btnFwd.innerHTML = `
    <span class="ctl-seek">
      <svg viewBox="0 0 24 24" width="7vw" height="7vw" fill="white"
           style="transform:scaleX(-1)">
        <path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4
                 c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/>
      </svg>
      <span class="ctl-n">10</span>
    </span>`;

  ctrlMid.appendChild(btnBack);
  ctrlMid.appendChild(btnPlay);
  ctrlMid.appendChild(btnFwd);

  // range slider (replaces div+fill — native input handles click position correctly)
  const track = pipWin.document.createElement('input');
  track.type = 'range'; track.id = 'track'; track.min = '0'; track.max = '1000'; track.step = '1'; track.value = '0';
  const time  = pipWin.document.createElement('div'); time.id = 'time'; time.textContent = '0:00 / 0:00';
  ctrlBot.appendChild(track);
  ctrlBot.appendChild(time);

  overlay.appendChild(ctrlMid);
  overlay.appendChild(ctrlBot);

  vwrap.appendChild(video);
  vwrap.appendChild(overlay);

  // ── Tracklist ─────────────────────────────────────────────────────────────
  const tlist = pipWin.document.createElement('div'); tlist.id = 'tlist';

  pipWin.document.body.appendChild(vwrap);
  pipWin.document.body.appendChild(tlist);

  // ── Controls ─────────────────────────────────────────────────────────────
  function updatePlayBtn() {
    const paused = video.paused;
    btnPlay.innerHTML = paused ? PLAY_SVG : PAUSE_SVG;
    btnPlay.title     = paused ? 'Play' : 'Pause';
  }
  video.addEventListener('play',  updatePlayBtn);
  video.addEventListener('pause', updatePlayBtn);
  btnPlay.addEventListener('click', () => { if (video.paused) video.play(); else video.pause(); });
  updatePlayBtn();

  btnBack.addEventListener('click', () => { video.currentTime = Math.max(0, video.currentTime - 10); });
  btnFwd.addEventListener('click',  () => { video.currentTime = Math.min(video.duration || 0, video.currentTime + 10); });

  // range input: fires continuously while dragging, position always correct
  let scrubbing = false;
  track.addEventListener('mousedown', () => { scrubbing = true; });
  track.addEventListener('mouseup',   () => { scrubbing = false; });
  track.addEventListener('input', () => {
    if (!video.duration) return;
    const pct = track.value / 1000;
    video.currentTime = pct * video.duration;
    track.style.setProperty('--pct', `${pct * 100}%`);
  });

  // ── Tick ─────────────────────────────────────────────────────────────────
  tickInterval = setInterval(() => {
    if (!video.duration || !pipWin || pipWin.closed) return;

    if (!scrubbing) {
      const pct = video.currentTime / video.duration;
      track.value = Math.round(pct * 1000);
      track.style.setProperty('--pct', `${(pct * 100).toFixed(2)}%`);
    }
    time.textContent = `${fmt(video.currentTime)} / ${fmt(video.duration)}`;

    let idx = -1;
    for (let i = parsedTimes.length - 1; i >= 0; i--) {
      if (parsedTimes[i] !== null && video.currentTime >= parsedTimes[i]) { idx = i; break; }
    }
    const rows = pipWin.document.querySelectorAll('#tscroll tbody tr');
    rows.forEach((tr, i) => {
      const wasActive = tr.classList.contains('active');
      tr.classList.toggle('active', i === idx);
      if (i === idx && !wasActive) {
        tr.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    });
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
    'background:#ff0000', 'color:#fff', 'border:none',
    'padding:10px 18px', 'border-radius:6px',
    'font:600 13px/1 system-ui,sans-serif',
    'cursor:pointer', 'box-shadow:0 2px 10px rgba(0,0,0,.6)',
    'transition:background .15s',
  ].join(';');
  fab.onmouseenter = () => { if (!fab.disabled) fab.style.background = '#cc0000'; };
  fab.onmouseleave = () => { if (!fab.disabled) fab.style.background = '#ff0000'; };

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
