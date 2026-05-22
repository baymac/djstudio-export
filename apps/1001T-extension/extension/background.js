'use strict';

const MAX_HISTORY = 20;

// Grant content scripts read access to chrome.storage.session (Chrome 115+).
// Without this, yt-content.js gets "Access to storage is not allowed from this context".
if (chrome.storage.session.setAccessLevel) {
  chrome.storage.session.setAccessLevel({ accessLevel: 'TRUSTED_AND_UNTRUSTED_CONTEXTS' })
    .catch((e) => console.warn('[bg] setAccessLevel failed:', e.message));
}

async function addToHistory(pip) {
  const { pip_history = [] } = await chrome.storage.local.get('pip_history');
  const updated = [pip, ...pip_history.filter(e => e.ytId !== pip.ytId)].slice(0, MAX_HISTORY);
  await chrome.storage.local.set({ pip_history: updated });
}

async function lookupHistory(ytId) {
  const { pip_history = [] } = await chrome.storage.local.get('pip_history');
  return pip_history.find(e => e.ytId === ytId) || null;
}

function sendWithRetry(tabId, payload) {
  const send = () => chrome.tabs.sendMessage(tabId, payload, () => void chrome.runtime.lastError);
  chrome.tabs.sendMessage(tabId, payload, () => {
    if (chrome.runtime.lastError) setTimeout(send, 1500);
  });
}

// ── 1001TL FAB click → open YouTube tab ──────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, _sender, _sendResponse) => {
  if (msg.type !== 'OPEN_YT_PIP') return;
  if (!msg.ytId) return;
  (async () => {
    const pip = { ytId: msg.ytId, tracks: msg.tracks, title: msg.title, tlUrl: msg.tlUrl };
    await chrome.storage.session.set({ pending_pip: pip });
    await addToHistory(pip);
    const tab = await chrome.tabs.create({ url: `https://www.youtube.com/watch?v=${pip.ytId}` });
    await chrome.storage.session.set({ pending_pip_tab_id: tab.id });
  })();
});

// ── Send SHOW_PIP_FAB once YouTube tab finishes loading ───────────────────────
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete') return;

  const stored = await chrome.storage.session.get(['pending_pip_tab_id', 'pending_pip']);

  // Primary: freshly-opened YouTube tab
  if (stored.pending_pip_tab_id === tabId) {
    await chrome.storage.session.remove('pending_pip_tab_id');
    if (!stored.pending_pip) return;
    sendWithRetry(tabId, { type: 'SHOW_PIP_FAB', pending_pip: stored.pending_pip });
    return;
  }

  // History: YouTube tab refreshed — re-show FAB if we have history for this video
  if (!tab?.url) return;
  let ytId;
  try { ytId = new URL(tab.url).searchParams.get('v'); } catch { return; }
  if (!ytId) return;
  const entry = await lookupHistory(ytId);
  if (!entry) return;
  sendWithRetry(tabId, { type: 'SHOW_PIP_FAB', pending_pip: entry });
});

// ── Keyboard shortcut Cmd/Ctrl+Shift+P ───────────────────────────────────────
chrome.commands.onCommand.addListener(async (command) => {
  if (command !== 'open-pip') return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url) return;

  if (/1001tracklists\.com\/tracklist\//.test(tab.url)) {
    chrome.tabs.sendMessage(tab.id, { type: 'GET_TRACKLIST' }, async (resp) => {
      if (chrome.runtime.lastError || !resp?.ok || !resp.ytId) return;
      const pip = { ytId: resp.ytId, tracks: resp.tracks, title: resp.title, tlUrl: resp.tlUrl };
      await chrome.storage.session.set({ pending_pip: pip });
      await addToHistory(pip);
      const newTab = await chrome.tabs.create({ url: `https://www.youtube.com/watch?v=${resp.ytId}` });
      await chrome.storage.session.set({ pending_pip_tab_id: newTab.id });
    });
    return;
  }

  if (/youtube\.com\/watch/.test(tab.url)) {
    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world:  'ISOLATED',
      func:   () => window.__ytTlPip?.enter(),
    });
  }
});
