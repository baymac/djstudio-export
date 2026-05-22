'use strict';

// Shared PiP utilities — loaded before content.js via manifest content_scripts.
// yt-pip.js (bookmarklet) keeps these inline; this file is the canonical source
// for the extension.

window.__pip = {
  BAR_H: 22,

  fmt(s) {
    const h   = Math.floor(s / 3600);
    const m   = Math.floor((s % 3600) / 60);
    const sec = Math.floor(s % 60);
    return h > 0
      ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
      : `${m}:${String(sec).padStart(2, '0')}`;
  },

  parseTime(str) {
    if (!str || str === '?') return null;
    const p = str.split(':').map(Number);
    if (p.length === 2) return p[0] * 60 + p[1];
    if (p.length === 3) return p[0] * 3600 + p[1] * 60 + p[2];
    return null;
  },

  // Build the <style> for a PiP window.
  // playerCSS: one extra rule for the player element (#vwrap > *)
  buildStyles(BAR_H, playerCSS) {
    return [
      '* { margin:0; padding:0; box-sizing:border-box; }',
      'html { width:100%; height:100%; }',
      'body { width:100%; height:100%; background:#000; overflow:hidden;',
      '       font-family:system-ui,sans-serif; display:flex; flex-direction:column; }',

      '#hdr  { flex:0 0 auto; display:flex; align-items:center; gap:1.5vw;',
      '        padding:0.6vw 2.2vw; background:#0a0a0a;',
      '        border-bottom:1px solid #1a1a1a; }',
      '#httl { flex:1 1 0; min-width:0; color:#666; font-size:2.5vw;',
      '        white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }',
      '#hlnk { flex:0 0 auto; color:#c02020; font-size:3.2vw;',
      '        text-decoration:none; line-height:1; }',
      '#hlnk:hover { color:#e03030; }',

      '#vwrap { flex:1 1 0; min-height:0; overflow:hidden; }',
      playerCSS,

      '#bar    { flex:0 0 ' + BAR_H + 'px; background:rgba(0,0,0,0.9);',
      '          display:flex; flex-direction:column;',
      '          justify-content:center; gap:3px; padding:0 2.2vw; }',
      '#track  { height:2px; background:rgba(255,255,255,0.2); border-radius:2px;',
      '          cursor:pointer; flex-shrink:0; }',
      '#fill   { height:100%; background:#c02020; border-radius:2px;',
      '          transform-origin:left; will-change:transform; }',
      '#time   { color:#888; font-size:2.8vw; line-height:1; }',

      '#tlist   { flex:0 0 60%; background:#0c0c0c;',
      '           border-top:1px solid #222; overflow:hidden;',
      '           display:flex; flex-direction:column; }',
      '#tscroll { flex:1 1 0; min-height:0; overflow-y:auto; overflow-x:hidden;',
      '           scrollbar-width:thin; scrollbar-color:#2a2a2a transparent; }',

      'table   { width:100%; border-collapse:collapse; font-size:2.8vw; }',
      'thead th { position:sticky; top:0; background:#0f0f0f;',
      '           color:#555; font-weight:600; font-size:2.34vw;',
      '           text-transform:uppercase; letter-spacing:.05em;',
      '           text-align:left; padding:0.9vw 1.5vw 0.6vw;',
      '           border-bottom:1px solid #1a1a1a; }',
      'td      { padding:0.6vw 1.5vw; vertical-align:top; line-height:1.4; }',
      'tr:hover td { background:rgba(255,255,255,0.05); }',
      'tr.active td { background:rgba(192,32,32,0.10); }',
      '.tn     { color:#333; width:5vw; font-size:2.5vw; }',
      '.tt     { color:#c02020; width:12.5vw; white-space:nowrap;',
      '          font-variant-numeric:tabular-nums; }',
      '.ta     { color:#999; width:36%; }',
      '.tk     { color:#ddd; }',
      'tr.tw td  { opacity:.65; }',
      'tr.tw .ta { color:#666; }',
      'i.wp    { font-style:italic; color:#555; margin-right:0.6vw; }',
    ].join('\n');
  },

  // Exact renderTracklist from yt-pip.js — works for any document (PiP or main).
  renderTracklist(doc, tracks) {
    const tlist = doc.getElementById('tlist');
    if (!tlist) { console.warn('[pip] #tlist not found'); return; }

    const tscroll = doc.createElement('div'); tscroll.id = 'tscroll';
    const table   = doc.createElement('table');

    const thead = doc.createElement('thead');
    const hrow  = doc.createElement('tr');
    [['#', 'tn'], ['Time', 'tt'], ['Artist', ''], ['Track', '']].forEach(([txt, cls]) => {
      const th = doc.createElement('th');
      if (cls) th.className = cls;
      th.textContent = txt;
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
      if (t.w) {
        const wp = doc.createElement('i'); wp.className = 'wp'; wp.textContent = 'w/ ';
        tdA.appendChild(wp);
      }
      tdA.appendChild(doc.createTextNode(t.artist));
      const tdK = doc.createElement('td'); tdK.className = 'tk'; tdK.textContent = t.track;

      tr.appendChild(tdN); tr.appendChild(tdT); tr.appendChild(tdA); tr.appendChild(tdK);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tscroll.appendChild(table);
    tlist.appendChild(tscroll);
  },
};
