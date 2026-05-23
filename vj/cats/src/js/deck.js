// Two-level deck:
//   Outer — fixed order: intro → cat → meow → catwoman, cycling.
//   Inner — each section's animations, 16–32 s each, shuffled.
// Section advance overrides any pending inner advance.
//
// Each section may carry an explicit `duration` (ms). The intro is short
// (6 s — matches the intro video length); the rest default to 2 minutes.

const DEFAULT_SECTION_DUR = 120000; // 2 minutes

const SECTIONS = [
  {
    name: 'intro',
    duration: 6000,        // 6 s — plays once at show start + after every full cycle
    anims: [
      { type: 'video', src: '/intro.mp4', label: 'INTRO', singlePlay: true },
    ],
  },
  {
    name: 'cat',
    anims: [
      { type: 'cat', pose: 'sleep' },
      { type: 'cat', pose: 'sit'   },
      { type: 'cat', pose: 'yoga'  },
      { type: 'cat', pose: 'cobra' },
      { type: 'cat', pose: 'run'   },
      { type: 'cat', pose: 'spin'  },
      { type: 'cat', pose: 'duet'  },
    ],
  },
  {
    name: 'meow',
    anims: [
      { type: 'meow', pose: 'nap'   },
      { type: 'meow', pose: 'walk'  },
      { type: 'meow', pose: 'stand' },
      { type: 'meow', pose: 'up'    },
      { type: 'meow', pose: 'dance' },
    ],
  },
  {
    name: 'catwoman',
    anims: [
      { type: 'video', src: '/scifi_cat.mp4',     label: 'CYBERPUNK' },
      { type: 'video', src: '/cinematic_cat.mp4', label: 'CYBORG'    },
    ],
  },
];

const animKey = a =>
  a.type === 'cat'  ? `cat-${a.pose}`
  : a.type === 'meow' ? `meow-${a.pose}`
  : (a.src || a.type);

function shuffleInner(arr, avoidKey) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  if (avoidKey && animKey(a[0]) === avoidKey && a.length > 1) {
    [a[0], a[1]] = [a[1], a[0]];
  }
  return a;
}

function randInner() { return 16000 + Math.random() * 16000; }

export function createDeck() {
  // Always start at intro (index 0); advance in fixed order
  let secIdx = 0;
  let curSec = SECTIONS[secIdx];

  let innerDeck = shuffleInner(curSec.anims, null);
  let innerIdx  = 0;
  let current   = innerDeck[innerIdx++];

  let innerDwell = 0;
  let innerMax   = randInner();
  let secDwell   = 0;

  function currentSectionDur() {
    return curSec.duration || DEFAULT_SECTION_DUR;
  }

  function startSection(sec) {
    curSec     = sec;
    secDwell   = 0;
    innerDeck  = shuffleInner(curSec.anims, null);
    innerIdx   = 0;
    current    = innerDeck[innerIdx++];
    innerDwell = 0;
    innerMax   = randInner();
  }

  function advanceSection() {
    secIdx = (secIdx + 1) % SECTIONS.length;
    startSection(SECTIONS[secIdx]);
  }

  function advanceInner() {
    if (innerIdx >= innerDeck.length) {
      innerDeck = shuffleInner(curSec.anims, animKey(current));
      innerIdx  = 0;
    }
    current    = innerDeck[innerIdx++];
    innerDwell = 0;
    innerMax   = randInner();
  }

  function tick(dt) {
    const ms = dt * 1000;
    secDwell   += ms;
    innerDwell += ms;

    if (secDwell >= currentSectionDur()) {
      advanceSection();
      return { anim: current, changed: true, sectionChanged: true };
    }
    if (innerDwell >= innerMax) {
      advanceInner();
      return { anim: current, changed: true, sectionChanged: false };
    }
    return { anim: current, changed: false, sectionChanged: false };
  }

  function skip()        { advanceInner();   return { anim: current, changed: true }; }
  function skipSection() { advanceSection(); return { anim: current, changed: true }; }

  // Reset the entire deck back to the start (intro section, fresh shuffle).
  // Used when the show is interrupted by silence — when music returns, the
  // cycle should restart cleanly rather than resume mid-section.
  function reset() {
    secIdx = 0;
    startSection(SECTIONS[secIdx]);
    return { anim: current, changed: true };
  }

  return {
    tick, skip, skipSection, reset,
    get current()          { return current; },
    get sectionName()      { return curSec.name; },
    get animLabel()        { return (current.label || current.pose || current.type || '').toUpperCase(); },
    get countdown()        { return Math.max(0, (innerMax - innerDwell) / 1000); },
    get sectionCountdown() { return Math.max(0, (currentSectionDur() - secDwell) / 1000); },
    get sectionProgress()  { return Math.max(0, Math.min(1, secDwell / currentSectionDur())); },
  };
}
