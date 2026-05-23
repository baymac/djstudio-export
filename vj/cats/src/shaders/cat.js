// Main Cat Scene — assembled from individual pose files in poses/
// Each pose is an independent state — no internal cycling.
// Dispatch: highest pose weight wins.
import helpers from './poses/cat_pose_helpers.js';
import sleep from './poses/cat_pose_sleep.js';
import sit from './poses/cat_pose_sit.js';
import run from './poses/cat_pose_run.js';
import yogaCat from './poses/cat_pose_yoga_cat.js';
import cobra from './poses/cat_pose_cobra.js';
import spin from './poses/cat_pose_stand.js';

// Extra helpers used by the spatial background:
//   bgHash — value noise hash (for stars + jitter)
//   sat    — clamp(x, 0, 1) shorthand
const bgHelpers = `
float bgHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float sat(float x)   { return clamp(x, 0.0, 1.0); }
`;

export default [
  `precision mediump float;

uniform float uTime;
uniform vec2  uResolution;
uniform float uSpeed;
uniform float uJump;
uniform float uPulse;
uniform float uEnergy;
uniform float uBeat;
uniform float uImpact;
uniform float uSwell;
uniform float uLow;
uniform float uMid;
uniform float uHigh;
uniform float uYaw;
uniform float uPitch;
uniform float uRoll;
uniform float uPoseRun;
uniform float uPoseSit;
uniform float uPoseSleep;
uniform float uPoseYoga;
uniform float uPoseCobra;
uniform float uPoseSpin;
uniform float uPoseDuet;
uniform float uTailSwish;
uniform float uHeadTilt;
uniform float uPoseTime;
uniform vec3  uCatColor;
`,
  helpers,
  bgHelpers,
  sleep,
  sit,
  run,
  yogaCat,
  cobra,
  spin,
  `void main() {
  vec2 uv = gl_FragCoord.xy / uResolution;
  vec2 p  = uv * 2.0 - 1.0;
  p.x    *= uResolution.x / uResolution.y;
  p       = rot2(p, uRoll * 0.8);
  p.x    += sin(p.y * 4.5 + uTime * (0.8 + uMid * 1.6)) * uImpact * 0.020;
  p.y    += uPitch * 0.35;
  p      *= 1.08 - uBeat * 0.02 + uSwell * 0.02;
  p.y    += 0.08;
  p.y    -= uJump;

  float density = mix(28.0, 42.0, clamp(uHigh * 0.6 + uSwell * 0.4, 0.0, 1.0));
  vec2  cellP   = p * density;
  vec2  cell    = fract(cellP) - 0.5;
  vec2  center  = (floor(cellP) + 0.5) / density;

  float mW = max(max(max(uPoseRun, uPoseSit),
             max(max(uPoseSleep, uPoseYoga),
             max(uPoseCobra, uPoseSpin))), uPoseDuet);

  vec3 catCol = uCatColor;
  float d;
  if (uPoseDuet >= mW - 0.001) {
    float duetScale = 0.55;
    float duetT = mod(uTime, 28.0);
    float leanGentle = sin(uTime * 0.18) * 0.012;
    float leanBig = (duetT > 24.0)
      ? smoothstep(24.0, 25.5, duetT) * smoothstep(28.0, 25.8, duetT) * 0.060
      : 0.0;
    float lean = leanGentle + leanBig;

    vec2 pL = (center - vec2(-0.215 + lean, -0.020)) / duetScale;
    pL.x = -pL.x;
    vec2 pR = (center - vec2( 0.215 - lean, -0.020)) / duetScale;
    float dL = catStand(pL);
    float dR = catStand(pR);
    d = min(dL, dR);
    if (dR < dL) catCol = vec3(0.74, 0.76, 0.82);
  }
  else if (uPoseSleep >= mW - 0.001) d = catSleep(center);
  else if (uPoseYoga  >= mW - 0.001) d = yogaCat(center, uPulse);
  else if (uPoseCobra >= mW - 0.001) d = yogaCobra(center, uPulse);
  else if (uPoseSpin  >= mW - 0.001) d = catStand(center);
  else if (uPoseSit   >= mW - 0.001) d = catSit(center);
  else                                d = catRun(center);

  float radius = length(p * vec2(0.90, 1.12));

  // ════════════════════════════════════════════════════════════════════════
  // Spatial background — denser flying particles forming per-pose geometric
  // formations, moving WITH the music (vj.html-style reactivity).
  // Per-particle position is weight-blended across all 7 pose formations
  // (sleep drift / sit orbits / yoga mandala / cobra zigzag / run streaks /
  // spin spiral / duet twin-clusters), then audio events perturb the
  // result: beats push particles outward radially, highs add micro-jitter,
  // impacts flash size + brightness, bass pumps orbital radii.
  // ════════════════════════════════════════════════════════════════════════

  // Audio-driven phase nudge: gentle, decays smoothly with uPulse so it
  // perturbs the phase but doesn't create discontinuities.
  float tau = uTime + uPulse * 0.30;

  // Beat / impact factors — used inside the loop to react per-particle
  float beatPush   = uPulse * 0.060 + uBeat * 0.040;     // outward radial shove
  float jitterAmp  = uHigh * 0.018 + uImpact * 0.012;    // hi-freq jitter
  float bassPump   = 1.0 + uLow * 0.18;                  // orbital radius pump
  float sizeFlash  = 1.0 + uBeat * 0.55 + uImpact * 0.50;
  float brightBeat = uSwell * 0.20 + uPulse * 0.18 + uImpact * 0.14;

  // Quiet base — faint catCol-warmed gradient.
  vec3 bg = vec3(0.018, 0.018, 0.030) + catCol * 0.025 * (0.55 + uSwell * 0.4);

  // 48 particles for denser bg.
  for (int i = 0; i < 48; i++) {
    float fi   = float(i);
    vec2 seed  = vec2(fi, 1.0);
    float h1   = bgHash(seed);
    float h2   = bgHash(seed + 13.0);
    float h3   = bgHash(seed + 27.0);
    float h4   = bgHash(seed + 41.0);

    // ── Per-pose formation positions ───────────────────────────────────

    // SLEEP — slowly drifting dust scatter
    vec2 pSleep = vec2(
      sin(tau * (0.05 + h1 * 0.06) + h2 * 6.2832) * (0.55 + h3 * 0.30),
      cos(tau * (0.04 + h2 * 0.05) + h3 * 6.2832) * (0.50 + h1 * 0.30)
    );

    // SIT — orbital rings at multiple radii; radius pumps with bass
    float orbitR   = (0.22 + h1 * 0.40) * bassPump;
    float orbitDir = (h3 > 0.5) ? 1.0 : -1.0;
    float orbitA   = tau * (0.20 + h2 * 0.55) * orbitDir + h4 * 6.2832;
    vec2 pSit = vec2(cos(orbitA), sin(orbitA)) * orbitR;

    // YOGA — 12-fold mandala formation (denser petals for more particles),
    // breathing radius in/out + slow rotation
    float petalIdx = floor(fi * 12.0 / 48.0);
    float petalA   = petalIdx * 0.5236 + tau * 0.14;   // 2π/12 = 0.5236
    float layer    = mod(fi, 4.0);
    float petalR   = (0.18 + layer * 0.14 + sin(tau * 0.6 + fi * 0.2) * 0.04) * bassPump;
    vec2 pYoga = vec2(cos(petalA), sin(petalA)) * petalR;

    // COBRA — zigzag dart paths, beat-synced tempo so jumps land on beats
    float zigSpeed = 0.5 + h1 * 0.4 + uPulse * 0.25;
    float zigT     = mod(tau * zigSpeed + h2, 2.0);
    float zigPhase = floor(zigT);
    float zigU     = fract(zigT);
    vec2 zigA = vec2((bgHash(seed + zigPhase * 3.0) - 0.5) * 1.7,
                     (bgHash(seed + zigPhase * 5.0) - 0.5) * 1.6);
    vec2 zigB = vec2((bgHash(seed + (zigPhase + 1.0) * 3.0) - 0.5) * 1.7,
                     (bgHash(seed + (zigPhase + 1.0) * 5.0) - 0.5) * 1.6);
    vec2 pCobra = mix(zigA, zigB, zigU);

    // RUN — horizontal hyperspace lanes, speed reacts to bass
    float laneY     = (h1 - 0.5) * 1.8;
    float laneSpeed = (1.0 + h2 * 2.5) * (1.0 + uLow * 0.6);
    float laneX     = mod(tau * laneSpeed + h3 * 4.0, 4.0) - 2.0;
    vec2 pRun = vec2(laneX, laneY);

    // SPIN — Archimedean spiral; rotation accelerates with pulse
    float spinA = fi * 0.55 + tau * (0.55 + uPulse * 0.45);
    float spinR = (mod(fi * 0.03 + tau * 0.25, 0.85) + 0.10) * bassPump;
    vec2 pSpin = vec2(cos(spinA), sin(spinA)) * spinR;

    // DUET — two clusters orbiting cat positions
    float side       = (fi < 24.0) ? -1.0 : 1.0;
    vec2  duetCenter = vec2(side * 0.215, -0.020);
    float duetR      = (0.12 + h2 * 0.22) * bassPump;
    float duetA      = tau * (0.40 + h3 * 0.50) + h4 * 6.2832;
    vec2 pDuet = duetCenter + vec2(cos(duetA), sin(duetA)) * duetR;

    // ── Weight-blend across all poses ──────────────────────────────────
    vec2 pPos = pSleep * uPoseSleep
              + pSit   * uPoseSit
              + pYoga  * uPoseYoga
              + pCobra * uPoseCobra
              + pRun   * uPoseRun
              + pSpin  * uPoseSpin
              + pDuet  * uPoseDuet;

    // ── Audio-driven perturbations ─────────────────────────────────────

    // Outward radial pulse on beat (like a shockwave pushing particles)
    float len = max(length(pPos), 0.04);
    pPos += (pPos / len) * beatPush;

    // High-frequency jitter (snares/hihats sparkle the particle field)
    pPos += vec2(
      sin(uTime * (9.0 + h1 * 7.0) + fi * 1.3),
      cos(uTime * (8.0 + h2 * 7.0) + fi * 1.7)
    ) * jitterAmp;

    // ── Particle shape: round / diamond / square (rotates by particle idx)
    vec2 lp        = p - pPos;
    float dist     = length(lp);
    float sizeBase = (0.008 + h1 * 0.005) * sizeFlash;
    int shapeI     = int(mod(fi, 3.0));
    float shape;
    if (shapeI == 0) {
      shape = exp(-dist * dist / (sizeBase * sizeBase));
    } else if (shapeI == 1) {
      float dia = abs(lp.x) + abs(lp.y);
      shape = smoothstep(sizeBase * 1.4, sizeBase * 0.5, dia);
    } else {
      float sq = max(abs(lp.x), abs(lp.y));
      shape = smoothstep(sizeBase * 1.2, sizeBase * 0.5, sq);
    }

    // Brightness — twinkle synced to time, audio adds boost on beats
    float twink  = 0.55 + 0.45 * sin(uTime * (1.0 + h3 * 3.0) + h2 * 60.0);
    float bright = (0.16 + brightBeat) * twink;
    vec3  pcol   = mix(catCol * 0.85, vec3(0.95, 0.95, 1.00), 0.30);
    bg += pcol * shape * bright;
  }

  // ── Dot grid for the cat silhouette (unchanged) ────────────────────────
  float dotR = 0.36 + uEnergy * 0.04 + uBeat * 0.05;
  float dot_ = smoothstep(dotR + 0.05, dotR - 0.05, length(cell));
  float mask = smoothstep(0.01, -0.01, d);
  float edge = smoothstep(0.045 + uImpact * 0.015, 0.0, abs(d));
  float innerGlow = smoothstep(0.12, 0.0, abs(d));
  vec3 catShade = mix(catCol * (0.62 + uLow * 0.22), catCol * (1.18 + uBeat * 0.25), edge);
  catShade += vec3(0.08, 0.10, 0.14) * innerGlow * (0.4 + uHigh * 0.5);
  // Glow halo around cat — uses catCol so it matches the dots
  vec3 glow = catCol * edge * (0.20 + uSwell * 0.30 + uBeat * 0.18);
  vec3 sceneCol = bg + glow;

  sceneCol = mix(sceneCol, catShade, dot_ * mask);
  sceneCol *= 1.0 - smoothstep(0.85, 1.35, radius) * 0.55;
  gl_FragColor = vec4(sceneCol, 1.0);
}
`,
].join('');
