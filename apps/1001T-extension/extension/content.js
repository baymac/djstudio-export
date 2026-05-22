'use strict';
// pip-core.js is loaded first by manifest and provides window.__pip

let cachedData = null; // { ytId, tracks, title, tlUrl }

// ── Page extraction ───────────────────────────────────────────────────────────
function getIdTL() {
  const m = location.pathname.match(/\/tracklist\/([^/]+)/);
  return m ? m[1] : null;
}

function getYouTubeVideoId() {
  for (const el of document.querySelectorAll('iframe')) {
    const src = el.src || el.dataset.src || '';
    const m = src.match(/youtube(?:-nocookie)?\.com\/embed\/([A-Za-z0-9_-]{11})/);
    if (m) return m[1];
  }
  for (const a of document.querySelectorAll('a[href]')) {
    let m = a.href.match(/youtube\.com\/watch\?v=([A-Za-z0-9_-]{11})/);
    if (m) return m[1];
    m = a.href.match(/youtu\.be\/([A-Za-z0-9_-]{11})/);
    if (m) return m[1];
  }
  const el = document.querySelector('[data-youtube-id],[data-yt-id],[data-video-id]');
  if (el) return el.dataset.youtubeId || el.dataset.ytId || el.dataset.videoId || null;
  return null;
}

function getTitle() {
  return (document.querySelector('h1')?.textContent || document.title).trim();
}

// ── Tracklist fetching ────────────────────────────────────────────────────────
async function fetchAPI(idTL) {
  const form = new FormData();
  form.append('object', 'tracklist');
  form.append('idTL', idTL);
  const res = await fetch('https://www.1001tracklists.com/ajax/export_data.php', {
    method: 'POST', body: form, credentials: 'include',
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const text = await res.text();
  try {
    const json = JSON.parse(text);
    if (Array.isArray(json))          return parseJSON(json);
    if (json.success === false)       throw new Error(json.message || 'API error');
    if (typeof json.data === 'string') return parseText(json.data);
    if (json.data)                    return parseJSON(json.data);
  } catch (e) {
    if (e.message === 'API error') throw e;
  }
  return parseText(text);
}

function stripEllipsis(s) { return s.replace(/^(?:\.{3}|…)\s*/, '').replace(/\.{3}$|…$/, '').trim(); }

// Remove header (event title) and footer (backlink notice) entries that 1001TL
// injects as the first/last lines with no timestamp and no artist.
function cleanTracks(tracks) {
  return tracks.filter((t) => {
    if (t.w) return true;
    // keep anything with a timestamp
    if (t.time) return true;
    // strip entries that are clearly metadata (no time, no artist)
    if (!t.artist) return false;
    return true;
  });
}

function parseJSON(data) {
  const raw = Array.isArray(data)
    ? data
    : (data.tracks || data.tracklist || Object.values(data));
  return raw.filter((t) => t && typeof t === 'object').map((t) => {
    let artist = stripEllipsis(t.artistName || t.artist || t.trackArtist || t.artist_name || '');
    let track  = stripEllipsis(t.trackName  || t.track  || t.trackTitle  || t.track_name  || t.name || t.title || '');
    const time = t.startTime  || t.time   || t.timestamp   || t.start_time  || '';
    const w    = !!(t.isWithTrack || t.type === 'with' || t.w || t.is_with);

    if (!artist && track.includes(' - ')) {
      const i = track.indexOf(' - ');
      artist = track.slice(0, i).trim();
      track  = track.slice(i + 3).trim();
    }
    return { time, artist, track, w };
  });
}

function parseText(text) {
  return text.split('\n').filter(Boolean).map((line) => {
    line = line.trim().replace(/^\d+\.\s*/, '');
    // export uses "...w/" or "… w/" as indented prefix for "with" sub-tracks
    const w = /^(?:\.{3}|…)?\s*w\//i.test(line);
    if (w) line = line.replace(/^(?:\.{3}|…)?\s*w\/\s*/i, '');
    const tm = line.match(/^[\[(]?(\d+:\d+(?::\d+)?)[\])]?\s+(.+)$/);
    let rest = line, time = '';
    if (tm) { time = tm[1]; rest = tm[2]; }
    const dash = rest.indexOf(' - ');
    return dash !== -1
      ? { time, artist: stripEllipsis(rest.slice(0, dash)), track: stripEllipsis(rest.slice(dash + 3)), w }
      : { time, artist: '', track: stripEllipsis(rest), w };
  });
}

function fullText(el) {
  if (!el) return '';
  // 1001TL wraps each artist in <a title="Full Name"> — collect all of them
  const links = el.querySelectorAll('a[title]');
  if (links.length) {
    const names = Array.from(links).map(a => a.title.trim()).filter(Boolean);
    if (names.length) return names.join(' & ');
  }
  const full = el.title?.trim() || el.getAttribute('aria-label')?.trim() || '';
  const text = stripEllipsis(el.textContent.trim());
  return full && full.length >= text.length ? full : text;
}

// Supplement artist names from DOM. The 1001TL DOM stores the canonical full
// name in <meta itemprop="byArtist" content="..."> inside each .tlpItem.
// Hidden tlpSubTog rows (mashup ingredients, .tgHid) aren't in the API export,
// so filter them out to keep positions aligned. Run on every track and pick
// the longer of {API, DOM} — the API often truncates without leaving "..."
// markers (e.g., "Hardwell & Olly Ja"), so checking for ellipsis isn't enough.
function supplementArtists(tracks) {
  const domItems = Array.from(document.querySelectorAll('.tlpItem'))
    .filter(el => !el.classList.contains('tgHid') && !el.classList.contains('tlpSubTog'));
  if (!domItems.length) return tracks;
  return tracks.map((t, i) => {
    const meta = domItems[i]?.querySelector('meta[itemprop="byArtist"]');
    const domArtist = meta?.content?.trim() || '';
    const apiArtist = stripEllipsis(t.artist || '');
    const artist = domArtist.length > apiArtist.length ? domArtist : apiArtist;
    return { ...t, artist };
  });
}

function scrapeDOM() {
  const items = document.querySelectorAll('.tlpItem');
  if (!items.length) return null;
  const tracks = [];
  items.forEach((item) => {
    const isWith   = item.classList.contains('tlpWith') || item.classList.contains('tw');
    const timeEl   = item.querySelector('.tlpTimestamp, [class*="time"]');
    const artistEl = item.querySelector('.tlpArtist,    [class*="artist"]');
    const trackEl  = item.querySelector('.tlpTrackName, [class*="track"]');
    tracks.push({
      time:   timeEl  ?.textContent.trim() || '',
      artist: fullText(artistEl),
      track:  fullText(trackEl) || item.textContent.trim(),
      w: isWith,
    });
  });
  return tracks.length ? tracks : null;
}

// ── FAB button ────────────────────────────────────────────────────────────────
function makeFabStyle() {
  return [
    'position:fixed', 'top:24px', 'right:24px', 'z-index:2147483647',
    'background:#c02020', 'color:#fff', 'border:none',
    'padding:10px 18px', 'border-radius:6px',
    'font:600 13px/1 system-ui,sans-serif',
    'cursor:pointer', 'box-shadow:0 2px 10px rgba(0,0,0,.6)',
    'transition:background .15s,opacity .15s',
  ].join(';');
}

function injectFab() {
  if (document.getElementById('tlPipFab')) return;
  if (!getIdTL()) return;

  const fab = document.createElement('button');
  fab.id = 'tlPipFab';
  fab.textContent = '▶ Open PiP';
  fab.style.cssText = makeFabStyle();
  fab.onmouseenter = () => { if (!fab.disabled) fab.style.background = '#e03030'; };
  fab.onmouseleave = () => { if (!fab.disabled) fab.style.background = '#c02020'; };

  fab.addEventListener('click', async () => {
    fab.textContent = 'Fetching…';
    fab.disabled = true;
    fab.style.background = '#888';
    fab.style.cursor = 'default';

    try {
      if (!cachedData) {
        const idTL  = getIdTL();
        const title = getTitle();
        const tlUrl = location.href;

        // YouTube iframe may be lazy-loaded — retry up to 5s
        let ytId = null;
        for (let i = 0; i < 10; i++) {
          ytId = getYouTubeVideoId();
          if (ytId) break;
          fab.textContent = `Waiting for video… (${i + 1})`;
          await new Promise(r => setTimeout(r, 500));
        }

        fab.textContent = 'Fetching tracklist…';
        let tracks = null;
        try { tracks = await fetchAPI(idTL); } catch (e) { console.warn('[1001tl-pip] API:', e.message); }
        if (!tracks?.length) tracks = scrapeDOM();
        if (tracks?.length) {
          const before = tracks.length;
          tracks = cleanTracks(tracks);
          const domItemCount = document.querySelectorAll('.tlpItem:not(.tgHid):not(.tlpSubTog)').length;
          const metaCount = document.querySelectorAll('.tlpItem meta[itemprop="byArtist"]').length;
          const apiArtists = tracks.slice(0, 10).map(t => (t.w ? 'w/ ' : '') + t.artist);
          tracks = supplementArtists(tracks);
          const finalArtists = tracks.slice(0, 10).map(t => (t.w ? 'w/ ' : '') + t.artist);
          console.log(`[1001tl-pip] parsed=${before} cleaned=${tracks.length} visibleDom=${domItemCount} metaTags=${metaCount}`);
          console.log('[1001tl-pip] from API:  ' + JSON.stringify(apiArtists));
          console.log('[1001tl-pip] after DOM: ' + JSON.stringify(finalArtists));
        }
        if (!tracks?.length) throw new Error('Could not get tracklist — try logging in');
        if (!ytId) throw new Error('No YouTube video found on this page');

        cachedData = { ytId, tracks, title, tlUrl };
      }

      fab.textContent = 'Opening YouTube…';
      chrome.runtime.sendMessage({ type: 'OPEN_YT_PIP', ...cachedData });
      setTimeout(() => fab.remove(), 1500);
    } catch (err) {
      console.error('[1001tl-pip]', err);
      fab.textContent = '✕ ' + err.message;
      fab.style.background = '#802020';
      fab.style.cursor = 'pointer';
      setTimeout(() => {
        fab.textContent = '▶ Open PiP';
        fab.style.background = '#c02020';
        fab.disabled = false;
      }, 3000);
    }
  });

  document.body.appendChild(fab);
}

injectFab();

// ── Legacy message handler (popup fallback) ───────────────────────────────────
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type !== 'GET_TRACKLIST') return;

  (async () => {
    if (cachedData) { sendResponse({ ok: true, ...cachedData }); return; }

    const idTL = getIdTL();
    if (!idTL) { sendResponse({ ok: false, error: 'No tracklist ID in URL' }); return; }

    const ytId  = getYouTubeVideoId();
    const title = getTitle();
    const tlUrl = location.href;

    let tracks = null;
    try   { tracks = await fetchAPI(idTL); }
    catch (e) { console.warn('[1001tl-pip] API:', e.message); }
    if (!tracks?.length) tracks = scrapeDOM();
    if (tracks?.length) tracks = supplementArtists(cleanTracks(tracks));
    if (!tracks?.length) {
      sendResponse({ ok: false, error: 'Could not get tracklist — try logging in' });
      return;
    }

    cachedData = { ytId, tracks, title, tlUrl };
    sendResponse({ ok: true, ...cachedData });
  })();

  return true;
});
