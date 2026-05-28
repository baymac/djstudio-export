# 1001TL PiP — Chrome Extension

> Part of the [`dj`](../../README.md) repo. See [Setup](../../README.md#setup) if you need to install the parent toolkit first.

PiP a DJ mix and see the tracklist while continuing your work. Opens a YouTube video in a floating Document Picture-in-Picture window with the full tracklist from 1001tracklists.com overlaid inside it — the mix and the IDs stay on top of whatever else you're doing.

![PiP window — YouTube video on top, scrollable tracklist below with active-track highlight](screenshot.png)

The screenshot above is a live capture of the PiP window for a Rüfüs Du Sol Sundowner mix: the YouTube player sits at the top of the floating window, and the full 1001TL tracklist scrolls below it with timestamps + artist + track name. The row matching the current playback time is highlighted, and the list auto-scrolls so the active track stays visible without manual scrubbing.

## How it works

1. Visit a tracklist page on 1001tracklists.com (e.g. `1001tracklists.com/tracklist/…`)
2. A red **"Open PiP + Tracklist"** button appears in the top-right corner
3. Click it → YouTube tab opens automatically
4. A second red button appears on the YouTube page — click it to open the PiP window
5. The floating window shows the video + scrollable tracklist; the current track highlights as it plays

The extension saves the last 20 tracklists locally, so the button reappears if you revisit a YouTube video without going through 1001TL again.

## Install (unpacked)

1. Open `chrome://extensions` (or `brave://extensions`)
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** and select the `extension/` folder
4. The extension is active — no toolbar button, it works purely via injected FABs

## Pack for distribution

```bash
dj extension pack 1001T
```

Zips `extension/` to `~/Music/dj/extensions/1001T-extension-v<version>.zip`
(version read from `manifest.json`). Use the zip for Chrome Web Store upload, for
sharing, or to load locally: drag the .zip onto `chrome://extensions` with
Developer mode on, or extract it and **Load unpacked** the resulting folder.
For a signed `.crx`, point chrome://extensions → **Pack extension** at the
extracted folder.

## Keyboard shortcut

`Cmd+Shift+P` (Mac) / `Ctrl+Shift+P` — opens PiP from whichever tab is active:
- On a 1001TL tracklist page: fetches data and opens YouTube
- On a YouTube watch page: opens the PiP window directly

## QA

Requires Node.js and Playwright. From this directory:

```bash
npm install
node qa-test.js
```

The test walks the full flow in a headed Chromium window and saves screenshots to `qa-screenshots/`.

## Files

```
extension/
  manifest.json     MV3 manifest
  background.js     Service worker — storage, tab management, history
  content.js        1001TL page — FAB injection + tracklist scraping
  yt-content.js     YouTube page — FAB injection + PiP orchestration
  pip-core.js       Shared utilities (time parsing, CSS, tracklist render)
  icons/            Extension icons (16/32/48/128 px)
qa-test.js          Playwright end-to-end QA script
package.json        Node dependencies (playwright)
screenshot.png      PiP window reference image (used in README + main repo docs)
```
