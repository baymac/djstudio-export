// Scene Manager — renders the current animation from the deck.
import vertex   from '../shaders/vertex.js';
import catFrag  from '../shaders/cat.js';
import meowFrag from '../shaders/meow.js';
import { createMeowAnim } from './meow_anim.js';
import { createDeck }     from './deck.js';

const FRAG = { cat: catFrag, meow: meowFrag };

export function createScene() {
  let p      = null;
  let assets = {};
  const compiled = {};
  let prevT  = null;

  const meowAnim    = createMeowAnim();
  const deck        = createDeck();
  let lastAnimKey   = null;

  function compile(p5, loadedAssets) {
    p      = p5;
    assets = loadedAssets || {};
    Object.keys(FRAG).forEach(k => {
      compiled[k] = p.createShader(vertex, FRAG[k]);
    });
  }

  function applyCatUniforms(s, w, h, t, u) {
    const pd = p.pixelDensity ? p.pixelDensity() : 1;
    s.setUniform('uTime',       t);
    s.setUniform('uResolution', [w * pd, h * pd]);
    s.setUniform('uJump',       u.uJump);
    s.setUniform('uPulse',      u.uPulse);
    s.setUniform('uEnergy',     u.uEnergy);
    s.setUniform('uBeat',       u.uBeat);
    s.setUniform('uImpact',     u.uImpact);
    s.setUniform('uSwell',      u.uSwell);
    s.setUniform('uLow',        u.uLow);
    s.setUniform('uMid',        u.uMid);
    s.setUniform('uHigh',       u.uHigh);
    s.setUniform('uSpeed',      u.uSpeed);
    s.setUniform('uYaw',        u.uYaw);
    s.setUniform('uPitch',      u.uPitch);
    s.setUniform('uRoll',       u.uRoll);
    s.setUniform('uPoseRun',    u.uPoseRun);
    s.setUniform('uPoseSit',    u.uPoseSit);
    s.setUniform('uPoseSleep',  u.uPoseSleep);
    s.setUniform('uPoseYoga',   u.uPoseYoga);
    s.setUniform('uPoseCobra',  u.uPoseCobra);
    s.setUniform('uPoseSpin',   u.uPoseSpin);
    s.setUniform('uPoseDuet',   u.uPoseDuet);
    s.setUniform('uCatColor',   u.uCatColor);
    s.setUniform('uHeadTilt',   u.uHeadTilt);
    s.setUniform('uTailSwish',  u.uTailSwish);
    s.setUniform('uPoseTime',   u.uPoseTime);
  }

  function applyMeowUniforms(s, w, h, t, u, meowState) {
    const pd = p.pixelDensity ? p.pixelDensity() : 1;
    s.setUniform('uTime',       t);
    s.setUniform('uResolution', [w * pd, h * pd]);
    s.setUniform('uPulse',      u.uPulse);
    s.setUniform('uEnergy',     u.uEnergy);
    s.setUniform('uBeat',       u.uBeat);
    s.setUniform('uImpact',     u.uImpact);
    s.setUniform('uSwell',      u.uSwell);
    s.setUniform('uLow',        u.uLow);
    s.setUniform('uMid',        u.uMid);
    s.setUniform('uHigh',       u.uHigh);

    // Pose textures: A = current pose, B = previous (during crossfade)
    const meowImgs = assets.meow || [];
    const a = meowImgs[meowState.pose]     || meowImgs[0];
    const b = meowImgs[meowState.prevPose] || a;
    if (a) s.setUniform('uMeowA', a);
    if (b) s.setUniform('uMeowB', b);

    s.setUniform('uBlend',     meowState.blend);
    s.setUniform('uPose',      meowState.pose);
    s.setUniform('uPos',       meowState.pos);
    s.setUniform('uRot',       meowState.rot);
    s.setUniform('uScl',       meowState.scl);
    s.setUniform('uShear',     meowState.shear);
    s.setUniform('uJitter',    meowState.jitter);
    s.setUniform('uTrail',     meowState.trail);
    s.setUniform('uSpinPhase', meowState.spinPhase);
  }

  function currentAnimKey(anim) {
    if (anim.type === 'cat')  return `cat:${anim.pose}`;
    if (anim.type === 'meow') return `meow:${anim.pose}`;
    return `${anim.type}:${anim.src || ''}`;
  }

  // Returns { anim, changed } — changed=true when deck advanced.
  // frozen=true: skip the deck tick (visual stays on current pose's shader).
  function draw(w, h, t, u, features, frozen) {
    const dt     = prevT !== null ? Math.min(0.1, t - prevT) : 0;
    prevT        = t;

    // Drive meow animator with current pose
    if (deck.current.type === 'meow') {
      meowAnim.setPose(deck.current.pose);
    }
    const meowState = meowAnim.tick(dt, t, features || {});

    const deckState = frozen
      ? { anim: deck.current, changed: false, sectionChanged: false }
      : deck.tick(dt, features);

    const animKey = currentAnimKey(deck.current);
    if (animKey !== lastAnimKey) lastAnimKey = animKey;

    const fragKey = deck.current.type === 'cat' ? 'cat'
                  : deck.current.type === 'meow' ? 'meow'
                  : null;
    const s = fragKey ? compiled[fragKey] : null;
    if (!s) return deckState;
    try {
      p.shader(s);
      if (fragKey === 'cat')  applyCatUniforms(s, w, h, t, u);
      else                    applyMeowUniforms(s, w, h, t, u, meowState);
      p.rect(-w / 2, -h / 2, w, h);
    } catch (_) {}

    return deckState;
  }

  // Advance deck timing without rendering — used when an overlay (e.g. video) is showing
  function tickOnly(dt, features) {
    return deck.tick(dt, features);
  }

  function skip()        { return deck.skip(); }
  function skipSection() { return deck.skipSection(); }
  function reset()       { lastAnimKey = null; prevT = null; return deck.reset(); }

  return {
    compile, draw, tickOnly, skip, skipSection, reset,
    get current()          { return deck.current; },
    get sectionName()      { return deck.sectionName; },
    get animLabel()        { return deck.animLabel; },
    get countdown()        { return deck.countdown; },
    get sectionCountdown() { return deck.sectionCountdown; },
  };
}
