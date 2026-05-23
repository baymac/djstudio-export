import p5      from 'p5';
import { createAudio }       from './audio.js';
import { createState }       from './state.js';
import { createScene }       from './scene.js';
import { createUI    }       from './ui.js';
import { createVideoPlayer } from './video_player.js';
import meowNapUrl   from '../assets/meow/nap.png';
import meowWalkUrl  from '../assets/meow/walk.png';
import meowStandUrl from '../assets/meow/stand.png';
import meowUpUrl    from '../assets/meow/up.png';
import meowDanceUrl from '../assets/meow/dance.png';

const MEOW_URLS = [meowNapUrl, meowWalkUrl, meowStandUrl, meowUpUrl, meowDanceUrl];

const audio  = createAudio();
const state  = createState();
const scene  = createScene();

// On GitHub Pages the deployed base is e.g. '/touch-designer/'; locally it's '/'.
// Deck `src` strings stay stable ('/scifi_cat.mp4'); only the URL passed to the
// <video> element gets the base prefix.
const ASSET_BASE = import.meta.env.BASE_URL;
const assetUrl = (src) => ASSET_BASE + src.replace(/^\//, '');
const videos = {
  '/scifi_cat.mp4':     createVideoPlayer(assetUrl('/scifi_cat.mp4')),
  '/cinematic_cat.mp4': createVideoPlayer(assetUrl('/cinematic_cat.mp4')),
  // Intro plays once at show start + after every full cycle; no ping-pong.
  '/intro.mp4':         createVideoPlayer(assetUrl('/intro.mp4'), { pingPong: false }),
};
let activeVideo = null;

let ui            = null;
let lastFrameTime = 0;
const assets      = {};

// Duet label timing: labels are visible only when all of these are true:
//   1. The current pose is duet
//   2. Music is playing (not silent → cats are actually on screen, not rest poster)
//   3. uPoseTime ≥ 1.8 s (cats had time to fade in)
//   4. ≥ 2.5 s remain in the pose (labels fade out before cats vanish)
// uPoseTime only advances during non-silent frames (state.update is gated on
// silent in p.draw), so the 1.8 s show delay naturally pauses through silence.
const DUET_LABEL_SHOW_DELAY = 1.8;   // seconds (uPoseTime is in seconds)
const DUET_LABEL_HIDE_BEFORE = 2.5;  // seconds before pose ends
let duetActive      = false;
let duetLabelsShown = false;

// Rest screen only appears after this many seconds of continuous silence.
// Prevents a flash on page reload while audio is reconnecting.
const REST_SILENCE_DELAY = 1.5;
let silenceDuration = 0;
let inRestScreen    = false;   // tracks whether the static rest screen is currently up

// When N/M is pressed, show the target section's visuals for 6 s even if silent.
let manualPreview      = false;
let manualPreviewTimer = null;
function setManualPreview() {
  manualPreview = true;
  clearTimeout(manualPreviewTimer);
  manualPreviewTimer = setTimeout(() => { manualPreview = false; }, 6000);
}

// Display rotation for sideways-mounted projectors. The canvas always renders
// in 9:16 portrait internally; CSS rotation displays it sideways on the host
// monitor so a 90°-rotated projector shows it upright. Set via ?rot=90 (CW),
// ?rot=-90 (CCW), or 180 (flip). Press R at runtime to cycle through values.
const ROTATIONS = [0, 90, -90, 180];
function readInitialRotation() {
  const raw = parseInt(new URLSearchParams(location.search).get('rot') || '0', 10);
  return ROTATIONS.includes(raw) ? raw : 0;
}
let rotation = readInitialRotation();
let canvasEl = null;

function calcCanvas() {
  const winW = window.innerWidth;
  const winH = window.innerHeight;
  const aspect = 9 / 16;
  // For 90/-90 rotation, the long axis of the 9:16 canvas becomes horizontal
  // on screen, so it must fit screen width; the short axis must fit screen height.
  if (rotation === 90 || rotation === -90) {
    let ch = winW;                       // long axis = screen width post-rotate
    let cw = Math.floor(winW * aspect);  // short axis
    if (cw > winH) { cw = winH; ch = Math.floor(winH / aspect); }
    return { w: cw, h: ch };
  }
  // Default (or 180): portrait canvas, long axis fills screen height
  let cw = Math.floor(winH * aspect);
  let ch = winH;
  if (cw > winW) { cw = winW; ch = Math.floor(winW / aspect); }
  return { w: cw, h: ch };
}

function applyRotation() {
  const t = `translate(-50%, -50%) rotate(${rotation}deg)`;
  if (canvasEl) canvasEl.style.transform = t;
  Object.values(videos).forEach(v => v.setRotation(rotation));
  const sized = ['duet-labels', 'rest-screen'];
  for (const id of sized) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.style.transform = t;
    if (rotation === 90 || rotation === -90) {
      el.style.width  = 'min(100vh, 100vw * 9 / 16)';
      el.style.height = 'min(100vw, 100vh * 16 / 9)';
    } else {
      el.style.width  = 'min(100vw, 100vh * 9 / 16)';
      el.style.height = 'min(100vh, 100vw * 16 / 9)';
    }
  }
}

function hideAllVideos() {
  Object.values(videos).forEach(v => { if (v.active) v.hide(); });
  activeVideo = null;
}

function clearDuetLabels() {
  duetActive      = false;
  duetLabelsShown = false;
  ui?.hideDuetLabels();
}

// Track the previous anim type so we know when we're crossing from a
// non-cat section into the cat section — that's when the pose blender
// should snap rather than lerp.
let lastAnimType = null;

function handleAnimChange(anim) {
  const enteringCatFromOutside = anim.type === 'cat' && lastAnimType !== 'cat';
  if (anim.type === 'cat') {
    state.setPose(anim.pose, enteringCatFromOutside);
    hideAllVideos();
    if (anim.pose === 'duet') {
      // Mark active; the visibility check in p.draw will reveal labels once
      // poseTime crosses the show delay AND we're not silent.
      duetActive      = true;
      duetLabelsShown = false;
      ui?.hideDuetLabels();
    } else {
      clearDuetLabels();
    }
  } else if (anim.type === 'video') {
    const src = anim.src || '/scifi_cat.mp4';
    const player = videos[src];
    if (!player) { hideAllVideos(); clearDuetLabels(); return; }
    // Hide any other video that may be playing
    Object.entries(videos).forEach(([k, v]) => { if (k !== src && v.active) v.hide(); });
    const { w, h } = calcCanvas();
    player.show(w, h);
    activeVideo = player;
    clearDuetLabels();
  } else {
    hideAllVideos();
    clearDuetLabels();
  }
  lastAnimType = anim.type;
}

function anyVideoActive() {
  return Object.values(videos).some(v => v.active);
}

const sketch = (p) => {
  p.preload = () => {
    assets.meow = MEOW_URLS.map(url =>
      p.loadImage(url, () => {}, () => {})
    );
  };

  p.setup = () => {
    const { w, h } = calcCanvas();
    const cnv = p.createCanvas(w, h, p.WEBGL);
    cnv.style('position', 'fixed');
    cnv.style('top', '50%');
    cnv.style('left', '50%');
    cnv.style('z-index', '0');
    canvasEl = cnv.elt;
    applyRotation();
    requestAnimationFrame(() => {
      document.getElementById('prerot')?.remove(); // lifts opacity:0!important so inline opacity can take effect
      canvasEl.style.opacity = '1';
    });
    p.noStroke();
    scene.compile(p, assets);
    lastFrameTime = p.millis();
    ui = createUI(audio);
    handleAnimChange(scene.current);
    tryAutoConnect();
  };

  p.draw = () => {
    audio.resume(); // no-op if running; un-suspends after auto-connect with no click
    const now      = p.millis();
    const dt       = Math.min(0.1, (now - lastFrameTime) / 1000);
    lastFrameTime  = now;
    const features = audio.tick();

    const silent = features.energy < 0.05;
    if (silent) silenceDuration += dt;
    else        silenceDuration  = 0;
    // Music-off rest state: silence has persisted long enough that we should
    // force the static logo display. Suppressed during manual preview (N/M)
    // so the user can scrub through sections without it kicking in.
    const wantRest = silenceDuration >= REST_SILENCE_DELAY && !manualPreview;

    if (silent && !manualPreview) {
      if (wantRest) {
        // Music is off → force static logo display.
        // Hide any running video (intro / scifi / cinematic) and clear
        // any overlay labels — nothing should be animating.
        if (!inRestScreen) {
          hideAllVideos();
          clearDuetLabels();
          ui?.showRestScreen();
          inRestScreen = true;
          // Music stopped → reset the show so when audio returns it restarts
          // cleanly from the intro instead of resuming mid-section.
          scene.reset();
          state.reset();
          lastAnimType = null;
        }
      } else {
        // Brief silence window (< 1.5 s): don't show the rest screen yet —
        // this keeps page-reload audio reconnects from flashing the static.
        ui?.hideRestScreen();
      }
      // Deck is frozen — dt=0 keeps current pose pinned; no advance.
      scene.tickOnly(0, features);
    } else {
      // Music came back (or never stopped). If we were in rest, restore
      // whatever the deck is on now (re-shows videos, restores cat/meow).
      if (inRestScreen) {
        ui?.hideRestScreen();
        inRestScreen = false;
        handleAnimChange(scene.current);
      } else {
        ui?.hideRestScreen();
      }
      state.update(features, dt);
      if (!anyVideoActive()) {
        const result = scene.draw(p.width, p.height, now / 1000, state.uniforms, features);
        if (result?.changed) handleAnimChange(scene.current);
      } else {
        const result = scene.tickOnly(dt, features);
        if (result?.changed) handleAnimChange(scene.current);
      }
    }

    // Duet labels: shown only when the duet visual is actually on-screen.
    // Polled every frame; resilient to silence transitions and rest screen.
    const wantDuetLabels =
      duetActive
      && !silent
      && state.uniforms.uPoseTime >= DUET_LABEL_SHOW_DELAY
      && scene.countdown > DUET_LABEL_HIDE_BEFORE;
    if (wantDuetLabels !== duetLabelsShown) {
      if (wantDuetLabels) ui?.showDuetLabels();
      else                ui?.hideDuetLabels();
      duetLabelsShown = wantDuetLabels;
    }

    const debugStateLabel = inRestScreen
      ? 'REST'
      : (scene.sectionName === 'cat' ? state.label : scene.animLabel);
    ui?.updateDebug(
      features,
      debugStateLabel,
      inRestScreen ? null : scene.countdown,
      inRestScreen ? 'rest' : scene.sectionName,
      inRestScreen ? null : scene.sectionCountdown,
    );
  };

  p.keyPressed = () => {
    audio.resume();
    if (p.key === 'f' || p.key === 'F') ui?.toggleFullscreen();
    if (p.key === 'd' || p.key === 'D') ui?.toggleDebug();
    if (p.key === 'n' || p.key === 'N') {
      setManualPreview();
      const result = scene.skipSection();
      handleAnimChange(result.anim);
    }
    if (p.key === 'm' || p.key === 'M') {
      setManualPreview();
      const result = scene.skip();
      handleAnimChange(result.anim);
    }
    if (p.key === 'r' || p.key === 'R') {
      const idx = ROTATIONS.indexOf(rotation);
      rotation = ROTATIONS[(idx + 1) % ROTATIONS.length];
      const { w, h } = calcCanvas();
      p.resizeCanvas(w, h);
      Object.values(videos).forEach(v => v.resize(w, h));
      applyRotation();
    }
  };

  p.windowResized = () => {
    const { w, h } = calcCanvas();
    p.resizeCanvas(w, h);
    Object.values(videos).forEach(v => v.resize(w, h));
    applyRotation();
  };
};

async function tryAutoConnect() {
  const saved = localStorage.getItem('rbShowDevice') || null;
  try {
    await audio.init(saved);
    ['click', 'keydown', 'touchstart'].forEach(evt =>
      document.addEventListener(evt, () => {
        audio.resume();
        if (activeVideo) activeVideo.tryPlay();
      }, { once: true })
    );
  } catch (_) {
    ui?.showSetup();
  }
}

new p5(sketch);
