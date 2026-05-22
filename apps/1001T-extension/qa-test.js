/**
 * QA test for 1001TL PiP extension.
 * Runs headed Chromium with the extension loaded, extracts Brave cookies,
 * walks the full flow and screenshots every key step.
 */
const { chromium } = require('playwright');
const { execSync }  = require('child_process');
const path = require('path');
const fs   = require('fs');

const EXT_PATH  = path.resolve(__dirname, 'extension');
const SHOTS_DIR = path.resolve(__dirname, 'qa-screenshots');
const TL_URL    = 'https://www.1001tracklists.com/tracklist/rwdzcy9/hardwell-edc-las-vegas-2025-2025.html';

fs.mkdirSync(SHOTS_DIR, { recursive: true });

// ── Extract Brave cookies ─────────────────────────────────────────────────────
function getCookies() {
  const out = execSync('python3 /tmp/extract_brave_cookies.py youtube.com 1001tracklists.com', {
    timeout: 30000,
  }).toString();
  return JSON.parse(out.split('\n').find(l => l.startsWith('[')));
}

async function shot(page, name) {
  const p = path.join(SHOTS_DIR, `${name}.png`);
  await page.screenshot({ path: p, fullPage: false });
  console.log('  📸', p);
  return p;
}

async function main() {
  console.log('\n=== 1001TL PiP Extension QA ===\n');

  // ── Load cookies ─────────────────────────────────────────────────────────────
  console.log('[1] Extracting Brave cookies…');
  const rawCookies = getCookies();
  console.log(`    Got ${rawCookies.length} cookies`);

  // Playwright expects sameSite to be 'Strict'|'Lax'|'None'
  const cookies = rawCookies.map(c => ({
    ...c,
    sameSite: ['Strict', 'Lax', 'None'].includes(c.sameSite) ? c.sameSite : 'Lax',
    expires: c.expires > 0 ? c.expires : undefined,
  }));

  // ── Launch browser with extension ────────────────────────────────────────────
  console.log('[2] Launching Chromium with extension…');
  console.log('    Extension path:', EXT_PATH);

  const ctx = await chromium.launchPersistentContext('', {
    headless: false,
    args: [
      `--disable-extensions-except=${EXT_PATH}`,
      `--load-extension=${EXT_PATH}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-infobars',
      '--disable-notifications',
    ],
    permissions: ['notifications'], // pre-grant so no prompt appears
    viewport: { width: 1280, height: 800 },
    ignoreHTTPSErrors: true,
  });

  // ── Import cookies ────────────────────────────────────────────────────────────
  console.log('[3] Importing cookies…');
  await ctx.addCookies(cookies);

  // ── Open 1001tracklists tracklist page ────────────────────────────────────────
  console.log('[4] Opening 1001TL tracklist page…');
  console.log('   ', TL_URL);
  const tlPage = await ctx.newPage();
  await tlPage.goto(TL_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await tlPage.waitForTimeout(3000);
  await shot(tlPage, '01-1001tl-loaded');

  // ── Wait for FAB ─────────────────────────────────────────────────────────────
  console.log('[5] Waiting for red FAB on 1001TL page…');
  try {
    await tlPage.waitForSelector('#tlPipFab', { timeout: 10000 });
    console.log('    ✅ FAB found on 1001TL page!');
    await shot(tlPage, '02-1001tl-fab-visible');
  } catch {
    console.log('    ❌ FAB NOT found on 1001TL page');
    // Check if we're on the right URL and if content script ran
    const url = tlPage.url();
    console.log('    Current URL:', url);
    const fabExists = await tlPage.evaluate(() => !!document.getElementById('tlPipFab'));
    const idTL = await tlPage.evaluate(() => {
      const m = location.pathname.match(/\/tracklist\/([^/]+)/);
      return m ? m[1] : null;
    });
    console.log('    FAB in DOM:', fabExists, '| idTL:', idTL);
    // Try to detect if content script ran at all
    const csRan = await tlPage.evaluate(() => typeof window.__pip !== 'undefined');
    console.log('    pip-core.js ran:', csRan);
    await shot(tlPage, '02-1001tl-no-fab');
    await ctx.close();
    process.exit(1);
  }

  // ── Capture console logs ─────────────────────────────────────────────────────
  tlPage.on('console', msg => {
    const t = msg.text();
    if (t.includes('1001tl') || t.includes('[pip]') || t.includes('PiP'))
      console.log('    [1001tl console]', msg.type(), t);
  });
  tlPage.on('pageerror', err => console.log('    [pageerror]', err.message));

  // ── Click the FAB — set up page listener FIRST ────────────────────────────────
  console.log('[6] Clicking 1001TL FAB…');
  const newPagePromise = ctx.waitForEvent('page', { timeout: 30000 });
  await tlPage.click('#tlPipFab');

  // Poll FAB state while fetch happens
  for (let i = 0; i < 20; i++) {
    await tlPage.waitForTimeout(500);
    const fabState = await tlPage.evaluate(() => {
      const fab = document.getElementById('tlPipFab');
      return fab ? { text: fab.textContent, disabled: fab.disabled } : { removed: true };
    });
    console.log(`    FAB [${i * 0.5}s]:`, JSON.stringify(fabState));
    if (fabState.removed) break;
    if (fabState.text?.startsWith('✕')) {
      console.log('    ❌ FAB shows error — stopping');
      await shot(tlPage, '03-1001tl-fab-error');
      await ctx.close();
      process.exit(1);
    }
  }
  await shot(tlPage, '03-1001tl-after-click');

  // Now collect the tab
  let ytPage = null;
  console.log('    Waiting for YouTube tab…');
  try {
    ytPage = await newPagePromise;
    console.log('    ✅ New tab opened:', ytPage.url() || '(loading…)');
  } catch {
    console.log('    ❌ No new tab opened within 30s');
    await ctx.close();
    process.exit(1);
  }

  // Capture console logs from YouTube tab immediately
  ytPage.on('console', msg => {
    const t = msg.text();
    if (t.includes('yt-tl-pip') || t.includes('[pip]'))
      console.log('    [yt console]', msg.type(), t);
  });
  ytPage.on('pageerror', err => console.log('    [yt pageerror]', err.message));

  // ── Wait for YouTube page to load ────────────────────────────────────────────
  console.log('[7] Waiting for YouTube to load…');
  await ytPage.waitForLoadState('domcontentloaded', { timeout: 30000 });
  await ytPage.waitForTimeout(3000);
  const ytUrl = ytPage.url();
  console.log('    URL:', ytUrl);
  await shot(ytPage, '03-youtube-loaded');

  // ── Check console logs from YouTube content script ────────────────────────────
  console.log('[8] Checking YouTube page state…');
  const pipState = await ytPage.evaluate(() => {
    return {
      // data-ytpip attr is set by content script (visible across worlds)
      csState:       document.documentElement.getAttribute('data-ytpip') || 'NOT SET - cs never ran',
      fabExists:     !!document.getElementById('ytTlPipFab'),
      ytdAppExists:  !!document.querySelector('ytd-app'),
      videoExists:   !!document.querySelector('video'),
      urlV:          new URL(location.href).searchParams.get('v'),
      htmlOuterLen:  document.documentElement.outerHTML.length,
    };
  });
  console.log('    Page state:', JSON.stringify(pipState, null, 2));

  // ── Check for auto-PiP or FAB ────────────────────────────────────────────────
  console.log('[9] Checking for auto-PiP or FAB (up to 15s)…');
  await ytPage.waitForTimeout(5000); // give auto-pip time to populate
  const pipCheck = await ytPage.evaluate(() => ({
    autoPipWin:    typeof window.__autoPipWin !== 'undefined',
    autoPipFailed: window.__autoPipFailed || null,
    autoPipData:   !!window.__autoPipData,
    fabExists:     !!document.getElementById('ytTlPipFab'),
    pipOpened:     typeof window.documentPictureInPicture !== 'undefined'
                     ? !!window.documentPictureInPicture.window
                     : 'api-unavailable',
  }));
  console.log('    PiP/FAB state:', JSON.stringify(pipCheck, null, 2));

  if (pipCheck.pipOpened === true) {
    console.log('    ✅ PiP opened AUTOMATICALLY — no button click needed!');
    await shot(ytPage, '04-youtube-auto-pip');
  } else if (pipCheck.fabExists) {
    console.log('    ✅ FAB visible as fallback (auto-PiP not supported or timed out)');
    await shot(ytPage, '04-youtube-fab-visible');
  } else {
    console.log('    ❌ Neither auto-PiP nor FAB found after 15s');
    const state2 = await ytPage.evaluate(() => ({
      csState:       document.documentElement.getAttribute('data-ytpip'),
      ytTlPipLoaded: typeof window.__ytTlPip !== 'undefined',
      ytdApp:        !!document.querySelector('ytd-app'),
      video:         !!document.querySelector('video'),
    }));
    console.log('    Extended state:', JSON.stringify(state2, null, 2));
    await shot(ytPage, '04-youtube-nothing');
    await ctx.close();
    process.exit(1);
  }

  // ── History path: reload YouTube tab and verify FAB reappears ────────────────
  console.log('[10] Reloading YouTube page (simulates restart / refresh)…');
  await ytPage.reload({ waitUntil: 'domcontentloaded' });
  await ytPage.waitForTimeout(3000);
  await shot(ytPage, '05-youtube-reloaded');
  try {
    await ytPage.waitForSelector('#ytTlPipFab', { timeout: 10000 });
    console.log('    ✅ FAB reappeared after reload (history path works)!');
    await shot(ytPage, '06-youtube-fab-after-reload');
  } catch {
    const st = await ytPage.evaluate(() => document.documentElement.getAttribute('data-ytpip'));
    console.log('    ❌ FAB did NOT reappear after reload. data-ytpip:', st);
    await shot(ytPage, '06-youtube-no-fab-after-reload');
    process.exit(1);
  }

  // ── Final state ───────────────────────────────────────────────────────────────
  console.log('\n=== Screenshots saved to:', SHOTS_DIR, '===\n');
  console.log('Leaving browser open for 5s so you can inspect…');
  await ytPage.waitForTimeout(5000);
  await ctx.close();
}

main().catch((e) => {
  console.error('\n💥 QA FAILED:', e.message);
  console.error(e.stack);
  process.exit(1);
});
