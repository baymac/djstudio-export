// MEOW Scene — five real cat photos (transparent PNG cutouts) treated as
// floating sprites with sparse audio-reactive geometric accents.
// No solid background washes — the cats are objects in space, not cards.
//
// uMeowA: active cat texture (current pose)
// uMeowB: outgoing cat texture (during a crossfade)
// uBlend: 0..1 mix from B to A
// uPose:  0=nap 1=walk 2=stand 3=up 4=dance
// uPos.xy: cat center in p-space
// uRot:    cat z-rotation
// uScl:    cat scale
// uShear:  vec2 skew (xy)
// uJitter: glitch displacement amount
// uTrail:  vec4 (x,y, alpha, scale) of one ghost trail copy
//
// p-space is aspect-corrected (matches existing cat shader conventions).
export default `
precision mediump float;

uniform float uTime;
uniform vec2  uResolution;
uniform sampler2D uMeowA;
uniform sampler2D uMeowB;
uniform float uBlend;
uniform int   uPose;

uniform float uPulse;
uniform float uEnergy;
uniform float uBeat;
uniform float uImpact;
uniform float uSwell;
uniform float uLow;
uniform float uMid;
uniform float uHigh;

uniform vec2  uPos;
uniform float uRot;
uniform float uScl;
uniform vec2  uShear;
uniform float uJitter;
uniform vec4  uTrail;

// OIIA-style spin (used when uPose == 2 / stand).
// uSpinPhase: 0 = crisp still cat, 1 = full spinning dark blob; animator ramps between.
uniform float uSpinPhase;

#define PI  3.14159265359
#define TAU 6.28318530718

float sat(float x) { return clamp(x, 0.0, 1.0); }
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

mat2 rot2(float a) {
  float c = cos(a), s = sin(a);
  return mat2(c, -s, s, c);
}

// Sample a transparent-PNG cat. Mask comes from the PNG's alpha channel —
// these are background-removed cutouts, not white-bg images.
vec4 sampleCat(sampler2D tex, vec2 p, vec2 cpos, float scl, float ang, vec2 shear) {
  vec2 local = p - cpos;
  local = rot2(-ang) * local;
  // Apply shear (audio-reactive skew)
  local.x += local.y * shear.x;
  local.y += local.x * shear.y;
  if (abs(local.x) > scl * 1.30 || abs(local.y) > scl * 1.30) return vec4(0.0);
  vec2 uv = clamp(local / scl * 0.5 + 0.5, 0.0, 1.0);
  uv.y = 1.0 - uv.y;
  vec4 col = texture2D(tex, uv);
  // Alpha is the cutout mask. Slight inset to avoid jaggy edges.
  float mask = smoothstep(0.04, 0.32, col.a);
  return vec4(col.rgb, mask);
}

// OIIA spin sampler. spinPhase 0 = crisp cat, 1 = dark motion-blurred blob.
// The OIIA meme alternates: cat sits still, then suddenly spins so fast that
// our eyes can't track frames — we see the time-average of all rotations,
// which reads as a darker, desaturated, slightly-compressed blob.
vec4 sampleCatSpin(sampler2D tex, vec2 p, vec2 cpos, float scl, float spinPhase, float wobble) {
  vec2 local = p - cpos;
  // Horizontal compression — a 3D cat rotating on Y averages narrower than the
  // crisp front-facing image. Gently oscillate the squish factor during spin so
  // the blob "breathes" between fatter (face-on moments) and thinner (edge-on
  // moments) instead of sitting as a perfectly static blob.
  float compressOsc = mix(0.62, 0.84, 0.5 + 0.5 * cos(wobble * 11.0));
  float compress    = mix(1.0, compressOsc, spinPhase);
  // Tiny vertical wobble during spin so it isn't dead-still
  local.y -= sin(wobble * 9.0) * spinPhase * 0.006 * scl;
  local.x /= compress;

  if (abs(local.x) > scl * 1.40 || abs(local.y) > scl * 1.30) return vec4(0.0);

  vec2 baseUV = clamp(local / scl * 0.5 + 0.5, 0.0, 1.0);
  baseUV.y = 1.0 - baseUV.y;

  // Subtle UV shift during spin: as the cat tumbles, the motion-blur center
  // drifts left/right between frames, giving the blob a faint tumbling feel
  // rather than looking like a static dark cat shape.
  baseUV.x += sin(wobble * 13.0) * spinPhase * 0.03;

  // Tap count + blur width grow with spinPhase. At spinPhase=0 we still take
  // taps but with zero offset → identical to a single sample (the crisp cat).
  float blurWidth = 0.16 * spinPhase;
  vec3 colSum = vec3(0.0);
  float aW = 0.0;
  float wSum = 0.0;
  const int TAPS = 13;
  for (int i = 0; i < TAPS; i++) {
    float ti = (float(i) - 6.0) / 6.0;            // -1..1
    float w  = exp(-ti * ti * 1.4);
    vec2 sUV = baseUV + vec2(ti * blurWidth, 0.0);
    if (sUV.x < 0.0 || sUV.x > 1.0) { wSum += w; continue; }
    vec4 sc = texture2D(tex, sUV);
    colSum += sc.rgb * sc.a * w;
    aW     += sc.a * w;
    wSum   += w;
  }
  if (aW < 1e-4) return vec4(0.0);
  vec3 col = colSum / aW;

  // Darken + desaturate during spin (averaging all 360° rotations of a colored
  // 3D model produces a darker, less-saturated apparent color).
  if (spinPhase > 0.001) {
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(col, vec3(lum), 0.62 * spinPhase);
    col *= mix(1.0, 0.45, spinPhase);
  }

  // Soften alpha edges as we ramp into spin → blob feel
  float aNorm = aW / wSum;
  float edgeLo = mix(0.04, 0.10, spinPhase);
  float edgeHi = mix(0.32, 0.50, spinPhase);
  float alpha = smoothstep(edgeLo, edgeHi, aNorm);
  return vec4(col, alpha);
}

// ─── Pose-specific accents ────────────────────────────────────────────────────
// All five bgs use a vj.html-style kaleidoscopic geometric base layer:
// polar-coordinate multi-frequency sin/cos products with N-fold symmetry,
// audio-reactive frequencies, and a rotating reference frame. Each pose
// stacks pose-specific accents (stars, grid, lightning, etc.) on top.

// Kaleidoscope pattern — vj.html "mandala" style.
//   n: symmetry count (4..12)
//   t: phase (radians)
//   bands: vec3(low, mid, high) audio energies in 0..1
// Returns a signed scalar pat in roughly -1..1.
float kaleidoMandala(vec2 p, float n, float t, vec3 bands) {
  float r = length(p);
  float a = atan(p.y, p.x);
  float sector = TAU / max(n, 1.0);
  float asym   = mod(a + PI, sector) * n;
  float pat = 0.55 * sin((10.0 + bands.x * 10.0) * r - t * 0.35)
                   * cos((2.0 + bands.y *  4.0) * asym + t * 0.25)
            + 0.35 * sin((18.0 + bands.z * 20.0) * r + (3.0 + bands.z * 4.0) * asym - t * 0.55);
  return pat;
}

// Plasma — multi-frequency sin sums in cartesian + radial space.
float kaleidoPlasma(vec2 p, float t, vec3 bands) {
  float r = length(p);
  return 0.25 * (
      sin(p.x * (2.0 + bands.x * 3.0) + t * 0.15)
    + sin(p.y * (3.0 + bands.y * 4.0) - t * 0.12)
    + sin((p.x + p.y) * (4.0 + bands.z * 6.0) + t * 0.10)
    + sin(r * (6.0 + (bands.x + bands.y) * 4.0) - t * 0.08)
  );
}

// Rotating square lattice — vj.html "lattice" style.
float kaleidoLattice(vec2 p, float t, vec3 bands) {
  float s   = 6.0 + bands.y * 10.0;
  float rot = t * 0.10;
  mat2  R   = mat2(cos(rot), -sin(rot), sin(rot), cos(rot));
  vec2  q   = R * p;
  float gx  = abs(fract(q.x * s) - 0.5);
  float gy  = abs(fract(q.y * s) - 0.5);
  float r   = length(p);
  return (1.0 - sat(min(gx, gy) * 18.0)) * (0.6 + 0.4 * sin(t * 0.25 + r * 3.0));
}

// NAP — slow 4-fold mandala over indigo nebula, with the original twinkling
// stars, aurora ribbon, crescent moon, and ascending dream-dust orbs on top.
vec3 accNap(vec2 p, float t) {
  vec3 col = vec3(0.0);
  float r = length(p);

  // ── Slow dreamy mandala base (4-fold)
  // Pattern modulates intensity but never drops to zero (vj.html approach:
  // 0.35 base + 0.65 * variation) so we never get black cuts.
  vec3 bands = vec3(uLow, uMid, uHigh);
  float pat = kaleidoMandala(p, 4.0, t * 0.4, bands * 0.6);
  float patN = 0.35 + 0.65 * sat(pat * 0.8 + 0.2);   // 0.35..1.0
  vec3 violet = vec3(0.30, 0.18, 0.55);
  vec3 cyan   = vec3(0.10, 0.40, 0.65);
  vec3 mandalaCol = mix(violet, cyan, sat(0.5 + 0.5 * sin(t * 0.18 + r * 2.0)));
  // Continuous coverage; only fades very gently at the very far corners.
  float mandalaFall = smoothstep(0.10, 0.90, r) * (1.0 - smoothstep(1.55, 1.85, r) * 0.4);
  col += mandalaCol * patN * mandalaFall * (0.32 + uSwell * 0.28);

  // ── Drifting nebula clouds (layered low-freq noise on top of mandala)
  vec2 q = p * 1.2 + vec2(t * 0.022, t * 0.015);
  float cloud = sin(q.x * 1.9 + sin(q.y * 1.6)) * cos(q.y * 1.3 - sin(q.x * 0.9));
  cloud = pow(clamp(cloud * 0.5 + 0.5, 0.0, 1.0), 1.3);
  vec3 nebula = mix(vec3(0.22, 0.10, 0.46), vec3(0.08, 0.30, 0.50), cloud);
  col += nebula * cloud * smoothstep(0.18, 1.05, r) * (0.22 + uSwell * 0.20);

  // ── Twinkling stars
  vec2 sg     = floor(p * 9.0);
  float sh    = hash(sg);
  vec2 sjit   = vec2(hash(sg + 17.3) - 0.5, hash(sg - 4.7) - 0.5) * 0.6;
  vec2 scell  = fract(p * 9.0) - 0.5 - sjit;
  float sd    = length(scell);
  float strength = smoothstep(0.86, 1.0, sh);
  float twink = 0.45 + 0.55 * sin(t * (1.4 + sh * 5.0) + sh * 60.0);
  col += vec3(0.88, 0.92, 1.00) * (exp(-sd * 90.0) + exp(-sd * 14.0) * 0.20)
                                * twink * strength * 2.0;

  // ── Aurora ribbon
  float ribY = sin(p.x * 1.2 + t * 0.30) * 0.40 + cos(p.x * 0.6 - t * 0.18) * 0.10;
  float ribbon = exp(-abs(p.y - ribY) * 9.0) * smoothstep(1.30, 0.45, r);
  vec3 ribCol  = mix(vec3(0.22, 0.55, 0.85), vec3(0.55, 0.32, 0.90),
                     sin(p.x * 0.7 + t * 0.32) * 0.5 + 0.5);
  col += ribCol * ribbon * (0.22 + uSwell * 0.30);

  // ── Crescent moon
  vec2 moonPos = vec2(0.55, -0.62);
  float moonD = length(p - moonPos);
  float moon  = max(0.0, exp(-moonD * 22.0) * 0.7
                       - exp(-length(p - (moonPos + vec2(0.03, 0.04))) * 28.0) * 0.7);
  col += vec3(0.96, 0.93, 0.82) * (moon + exp(-moonD * 5.0) * 0.05);

  // ── Ascending dream-dust orbs
  for (int i = 0; i < 5; i++) {
    float fi = float(i);
    float orbY = mod(t * (0.16 + fi * 0.035) + fi * 0.41, 2.2) - 1.1;
    float orbX = sin(t * (0.32 + fi * 0.07) + fi * 1.8) * 0.45 + (fi - 2.0) * 0.12;
    float orbD = length(p - vec2(orbX, orbY));
    float fade = smoothstep(-1.1, -0.6, orbY) * smoothstep(1.1, 0.55, orbY);
    col += vec3(0.78, 0.72, 1.05) * (exp(-orbD * 38.0) + exp(-orbD * 9.0) * 0.18)
                                  * fade * (0.55 + uSwell * 0.35);
  }

  return col;
}

// WALK — Tron-style geometric corridor.
// Layers: rotating mandala behind the sky + perspective grid floor + parallax
// skyline silhouettes + drifting neon diamonds + horizon glow + speed streaks.
vec3 accWalk(vec2 p, float t) {
  vec3 col = vec3(0.0);
  float scroll = t * (0.55 + uLow * 1.3 + uPulse * 0.3);
  float horizonY = -0.05;
  vec3 bands = vec3(uLow, uMid, uHigh);

  // ── Uniform full-canvas atmospheric kaleidoscope.
  // Spans entire canvas (not just upper) so the bottom isn't visually heavier.
  // Dim base values so nothing competes with the cat for focus.
  vec2 latP   = p * 1.2;
  float lat   = kaleidoLattice(latP, scroll * 0.35, bands);
  float mand  = kaleidoMandala(p, 6.0, scroll * 0.45, bands * 0.5);
  float pat   = 0.40 + 0.60 * sat(mix(lat, sat(mand * 0.5 + 0.5), 0.45));
  vec3 deepCol = vec3(0.06, 0.18, 0.13);
  vec3 hotCol  = vec3(0.18, 0.50, 0.32);
  vec3 latCol  = mix(deepCol, hotCol, pat);
  col += latCol * pat * (0.16 + uPulse * 0.18);

  // ── Perspective grid floor (below the horizon) — dimmed so it doesn't
  //   dominate the lower half. Cat stays as the brightness focal point.
  if (p.y < horizonY - 0.001) {
    float groundZ  = 0.45 / (horizonY - p.y);
    float fadeNear = smoothstep(-1.05, -0.35, p.y);
    float fadeFar  = 1.0 - smoothstep(8.0, 22.0, groundZ);
    float depthCoord = groundZ - scroll * 1.4;
    float depthLine  = smoothstep(0.06, 0.0, abs(fract(depthCoord) - 0.5) - 0.46);
    float sideCoord = p.x * groundZ * 1.2;
    float sideLine  = smoothstep(0.06, 0.0, abs(fract(sideCoord) - 0.5) - 0.46);
    // Muted grid color (was bright cyan-green; now dim teal)
    vec3 gridCol = mix(vec3(0.06, 0.22, 0.16), vec3(0.10, 0.36, 0.24), uPulse);
    col += gridCol * (depthLine + sideLine * 0.85) * fadeNear * fadeFar
                    * (0.22 + uPulse * 0.18);
    // Subtle floor wash
    col += vec3(0.03, 0.08, 0.06) * fadeNear * fadeFar * 0.25;
  }

  // ── Parallax skyline silhouettes (dimmed)
  float skyMask = smoothstep(horizonY, horizonY + 0.05, p.y);
  if (skyMask > 0.0) {
    for (int i = 0; i < 3; i++) {
      float fi    = float(i);
      float speed = 0.35 + fi * 0.25;
      float xs    = p.x + scroll * speed + fi * 0.5;
      float spacing = 0.55 - fi * 0.10;
      float seed = floor(xs / spacing);
      float h    = hash(vec2(seed, fi * 7.3));
      float topY = horizonY + 0.10 + h * (0.20 + fi * 0.06);
      float xLocal = abs(fract(xs / spacing) - 0.5);
      float widthFrac = 0.32 - fi * 0.04;
      float bldX = step(xLocal, widthFrac);
      float bldY = step(p.y, topY) * step(horizonY, p.y);
      float bld  = bldX * bldY;
      float depthFade = 1.0 - fi * 0.28;
      // Much darker silhouettes
      vec3  bldCol    = vec3(0.02, 0.10, 0.08) * depthFade;
      float winGrid   = step(0.55, hash(vec2(seed, floor((p.y - horizonY) * 30.0))));
      // Dimmer window glow
      vec3  winCol    = mix(vec3(0.10, 0.32, 0.22), vec3(0.18, 0.42, 0.28), uMid);
      col += bldCol * bld;
      col += winCol * bld * winGrid * (0.10 + uMid * 0.20) * depthFade;
    }
  }

  // ── Drifting diamonds (dimmed)
  float upperSky = smoothstep(0.20, 0.45, p.y);
  if (upperSky > 0.0) {
    for (int i = 0; i < 4; i++) {
      float fi = float(i);
      float speed = 0.18 + fi * 0.06;
      float dx = mod(p.x - scroll * speed + fi * 0.43, 1.0) - 0.5;
      float dy = p.y - (0.45 + fi * 0.10) - sin(t * 0.4 + fi * 1.5) * 0.04;
      float diamond = abs(dx) + abs(dy);
      float edge = smoothstep(0.05, 0.04, diamond) * smoothstep(0.025, 0.035, diamond);
      vec3 dCol = mix(vec3(0.08, 0.30, 0.20), vec3(0.18, 0.42, 0.28), fi * 0.25);
      col += dCol * edge * upperSky * (0.30 + uHigh * 0.30);
    }
  }

  // ── Horizon glow — much subtler so it doesn't form a bright "wall"
  float horiD = abs(p.y - horizonY);
  float horizonGlow = exp(-horiD * 28.0) * 0.30
                    + exp(-horiD * 7.0)  * 0.06;
  col += vec3(0.10, 0.30, 0.22) * horizonGlow * (0.30 + uSwell * 0.30);

  // ── Speed streaks (much dimmer, suggest motion without dominating)
  float streakY = abs(p.y - horizonY - 0.025);
  if (streakY < 0.04) {
    float streak = sin(p.x * 14.0 - scroll * 28.0);
    streak = pow(max(0.0, streak), 28.0);
    col += vec3(0.12, 0.32, 0.24) * streak * (0.18 + uPulse * 0.30);
  }

  return col;
}

// STAND — bold solar mandala (10-fold) + radial sun rays + beat-pulsed
// expanding rings + concentric petal patterns.
vec3 accStand(vec2 p, float t) {
  vec3 col = vec3(0.0);
  float r = length(p);
  float a = atan(p.y, p.x);
  vec3 bands = vec3(uLow, uMid, uHigh);

  // ── 10-fold solar mandala base.
  // Pattern modulates between dim and bright; a 0.35 base coverage means
  // every region of the canvas always has some warm ambient color, so we
  // never get the "black cuts" where the kaleido equation goes negative.
  float mand = kaleidoMandala(p, 10.0, t * 0.8, bands);
  float patN = 0.35 + 0.65 * sat(mand * 0.8 + 0.2);     // 0.35..1.0
  vec3 deepBronze = vec3(0.18, 0.07, 0.02);
  vec3 sunYellow  = vec3(1.00, 0.75, 0.30);
  vec3 sunOrange  = vec3(1.00, 0.45, 0.10);
  vec3 mandCol = mix(deepBronze, mix(sunOrange, sunYellow, patN), patN);
  // Continuous coverage with a soft inner clearing for the cat — no hard cutoffs.
  float centerFall = smoothstep(0.10, 0.50, r);
  float outerFall  = 1.0 - smoothstep(1.65, 2.00, r) * 0.30;   // never fully dark
  float fall = centerFall * outerFall;
  col += mandCol * patN * fall * (0.50 + uSwell * 0.45);

  // ── Crisp radial sun rays (high frequency overlay)
  float rays = pow(max(0.0, cos(a * 18.0 + t * 0.45 + uMid * 1.5)), 18.0);
  col += sunYellow * rays * fall * (0.40 + uPulse * 0.5);

  // ── Concentric petal-style rings expanding outward
  float petalRing = pow(max(0.0, sin(r * 14.0 - t * (0.8 + uPulse * 1.6))), 6.0);
  col += sunOrange * petalRing * fall * (0.20 + uBeat * 0.5);

  // ── Beat-pulsed ring sweep — bright, expands outward, decays
  float beatRingR = 0.45 + sin(t * 1.2) * 0.1 + uBeat * 0.18;
  float beatRing  = exp(-pow((r - beatRingR) * 22.0, 2.0));
  col += vec3(1.00, 0.85, 0.40) * beatRing * (0.15 + uBeat * 0.85);

  // ── Ambient warm wash — guarantees no region is fully black. Fades very
  //     gently with radius and is cheaper than any pattern, so it always
  //     paints the corners with a faint bronze tone.
  col += deepBronze * (0.55 + 0.45 * sin(t * 0.20 + r * 1.5)) * (0.50 + uSwell * 0.30);

  return col;
}

// UP — synthwave music-stage tuned for cat focus. The accents (EQ bars,
// shockwaves, light pillars, sparkles) are distributed across the whole
// canvas at low brightness so the cat reads as the obvious focal point.
vec3 accUp(vec2 p, float t) {
  vec3 col = vec3(0.0);

  vec3 cyan    = vec3(0.20, 0.90, 1.00);
  vec3 magenta = vec3(1.00, 0.20, 0.85);
  vec3 deepBg  = vec3(0.06, 0.02, 0.10);

  // ── Ambient deep-space wash — gentle, uniform, no bright zones
  col += deepBg * (0.55 + 0.45 * sin(t * 0.30 + p.y * 3.0)) * (0.5 + uSwell * 0.3);

  // ── 24-bar vertical EQ spectrum — much shorter + dimmer + spread out so
  //    they don't form a bright wall along the bottom. Bars stay in a thin
  //    band at the very bottom edge, like a subtle audio-meter ribbon.
  float aspect   = uResolution.x / uResolution.y;
  float barAreaW = aspect * 2.0;
  float barTotal = 24.0;
  float barWidth = barAreaW / barTotal;
  float barFloor = -1.05;
  float barIdx = floor((p.x + aspect) / barWidth);
  if (barIdx >= 0.0 && barIdx < barTotal) {
    float fi = barIdx;
    float barCenter = -aspect + (fi + 0.5) * barWidth;
    float distToBar = abs(p.x - barCenter);
    if (distToBar < barWidth * 0.36) {
      float bandT = fi / (barTotal - 1.0);
      float bandValue =
          (bandT < 0.34) ? uLow
        : (bandT < 0.67) ? uMid
        :                   uHigh;
      float anim = 0.45 + 0.55 * sin(t * (1.6 + fi * 0.13) + fi * 0.71);
      // Capped to 0.55 (was 1.7) — bars stay near the bottom edge
      float barHeight = clamp(0.05 + bandValue * 0.50 * anim
                              + uPulse * 0.10, 0.05, 0.55);
      float barTop = barFloor + barHeight;
      if (p.y >= barFloor && p.y <= barTop) {
        float vT      = (p.y - barFloor) / max(barHeight, 0.001);
        vec3  barCol  = mix(cyan, magenta, vT);
        float edgeSoft = 1.0 - smoothstep(barWidth * 0.30, barWidth * 0.36, distToBar);
        float intensity = 0.55 + 0.55 * vT;
        // Brightness cut to ~30% of original so bars don't dominate
        col += barCol * intensity * edgeSoft * (0.20 + uPulse * 0.18);
      }
      if (p.y > barTop && p.y < barTop + 0.06) {
        float gd = (p.y - barTop) / 0.06;
        float glow = (1.0 - gd) * (1.0 - gd);
        float edgeSoft = 1.0 - smoothstep(barWidth * 0.30, barWidth * 0.36, distToBar);
        col += magenta * glow * edgeSoft * (0.18 + uMid * 0.20);
      }
    }
  }

  // ── Concentric sound shockwaves from cat's mouth area — these naturally
  //    distribute across the whole canvas, so we keep them prominent.
  vec2 mouthPos = vec2(0.0, 0.35);
  float mouthD  = distance(p, mouthPos);
  for (int i = 0; i < 4; i++) {
    float fi    = float(i);
    float age   = mod(t * (0.55 + uPulse * 0.4) + fi * 0.25, 1.0);
    float shockR     = age * 1.6;
    float shockWidth = 0.025 + age * 0.10;
    float shock = exp(-pow((mouthD - shockR) / shockWidth, 2.0));
    float fade  = (1.0 - age) * smoothstep(0.0, 0.10, age);
    col += mix(magenta, cyan, age) * shock * fade * (0.20 + uBeat * 0.45);
  }

  // ── Vertical neon light pillars (parallax) — dimmed
  for (int i = 0; i < 5; i++) {
    float fi = float(i);
    float beamX = sin(t * (0.25 + fi * 0.07) + fi * 1.7) * 0.55 + (fi - 2.0) * 0.16;
    float beamD = abs(p.x - beamX);
    float beam  = exp(-beamD * 65.0);
    // Vertical fade now centered higher and softer (lifted 0.20 → 0.10) so
    // pillars don't pile up around the cat's body, distributing more uniformly.
    float yFade = exp(-pow((p.y - 0.10) * 1.2, 2.0));
    vec3 beamCol = mix(cyan, magenta, fi * 0.25);
    col += beamCol * beam * yFade * (0.16 + uLow * 0.22);
  }

  // ── Drifting sparkles — distributed across whole canvas (not just rising)
  for (int i = 0; i < 9; i++) {
    float fi    = float(i);
    float orbT  = mod(t * (0.18 + fi * 0.04) + fi * 0.31, 1.0);
    float sparkX = sin(t * 0.35 + fi * 2.1) * 0.60 + cos(t * 0.27 + fi) * 0.25;
    float sparkY = sin(t * 0.42 + fi * 1.7) * 0.85 + cos(t * 0.19 + fi * 0.6) * 0.20;
    float sparkD = length(p - vec2(sparkX, sparkY));
    float spark  = exp(-sparkD * 90.0) + exp(-sparkD * 22.0) * 0.10;
    float twink  = 0.4 + 0.6 * sin(t * (1.6 + fi * 0.3) + fi * 4.0);
    col += mix(cyan, magenta, fi * 0.13) * spark * twink * (0.30 + uHigh * 0.35);
  }

  // ── Faint full-canvas plasma haze — keeps upper area populated
  vec3 bands = vec3(uLow, uMid, uHigh);
  float haze = kaleidoPlasma(p * 0.7, t * 0.4, bands * 0.5);
  float hazeN = 0.40 + 0.60 * sat(haze * 0.7 + 0.2);
  col += mix(magenta, cyan, sin(t * 0.2 + p.y * 2.0) * 0.5 + 0.5)
       * hazeN * 0.06 * (0.6 + uSwell * 0.5);

  // ── Subtle scanline shimmer
  float scan = 0.96 + 0.04 * sin(p.y * 240.0);
  col *= scan;

  return col;
}

// DANCE — full chromatic kaleidoscope: 6-fold mandala + rotating lattice +
// plasma overlay + beat bursts. The most maximalist of all poses.
vec3 accDance(vec2 p, float t) {
  vec3 col = vec3(0.0);
  float r = length(p);
  float a = atan(p.y, p.x);
  vec3 bands = vec3(uLow, uMid, uHigh);

  // ── Spinning frame base
  float rot = t * (0.25 + uPulse * 0.5);
  vec2 pRot = rot2(rot) * p;

  // ── 6-fold mandala kaleidoscope (primary)
  float mand = kaleidoMandala(pRot, 6.0, t * 1.2, bands);
  // ── Counter-rotating lattice (secondary, finer detail)
  float lat  = kaleidoLattice(rot2(-rot * 0.6) * p, t, bands);
  // ── Plasma overlay (color motion)
  float plas = kaleidoPlasma(pRot * 1.4, t * 0.8, bands);

  // Color: cycling through magenta → cyan → lime
  float hueT = sin(t * 0.4 + r * 3.0) * 0.5 + 0.5;
  vec3 magenta = vec3(0.95, 0.20, 0.85);
  vec3 cyan    = vec3(0.20, 0.85, 0.95);
  vec3 lime    = vec3(0.50, 0.95, 0.30);
  vec3 huedA   = mix(magenta, cyan, hueT);
  vec3 huedB   = mix(cyan,    lime, sin(t * 0.27 + 1.7) * 0.5 + 0.5);

  // Continuous coverage — gentle inner clearing, no hard outer cut
  float fall   = smoothstep(0.20, 0.65, r) * (1.0 - smoothstep(1.55, 1.95, r) * 0.25);
  // Composite the three patterns; base coverage so corners always have color
  float combined = 0.30 + 0.70 * sat(
      sat(mand * 0.5 + 0.5) * 0.55 + lat * 0.35 + plas * 0.25
    );
  col += huedA * combined * fall * (0.55 + uSwell * 0.55);
  col += huedB * (0.30 + 0.70 * sat(lat)) * fall * (0.20 + uPulse * 0.40);

  // ── Beat-snap radial bursts (cyan flashes on each beat)
  float burst = pow(max(0.0, sin(a * 6.0 + t * 2.5)), 20.0);
  col += cyan * burst * fall * (0.25 + uBeat * 0.95);

  // ── Outer shockwave ring on impact
  float shockR  = 0.55 + uBeat * 0.18;
  float shock   = exp(-pow((r - shockR) * 14.0, 2.0));
  col += magenta * shock * uImpact * 0.7;

  // ── Ambient chromatic wash — every corner has color
  col += mix(magenta, cyan, sin(t * 0.4 + r * 3.0) * 0.5 + 0.5) * 0.10
       * (0.6 + 0.4 * sin(t * 0.8 + r * 2.0));

  return col;
}

vec3 accents(vec2 p, float t) {
  if      (uPose == 0) return accNap(p, t);
  else if (uPose == 1) return accWalk(p, t);
  else if (uPose == 2) return accStand(p, t);
  else if (uPose == 3) return accUp(p, t);
  else                 return accDance(p, t);
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution;
  vec2 p  = uv * 2.0 - 1.0;
  p.x    *= uResolution.x / uResolution.y;

  // Subtle global wobble (audio-reactive screen distortion)
  vec2 pAccents = p;
  pAccents.x += sin(p.y * 5.0 + uTime * (0.7 + uMid * 1.5)) * uImpact * 0.020;
  pAccents.y += cos(p.x * 4.0 - uTime * (0.5 + uLow * 1.2)) * uPulse * 0.012;

  // Glitch: chunked horizontal slice displacement on impact
  vec2 pCat = p;
  if (uJitter > 0.001) {
    float slice = floor(p.y * 18.0);
    float jh = hash(vec2(slice, floor(uTime * 22.0)));
    if (jh > 0.55) pCat.x += (jh - 0.55) * uJitter * 0.6;
  }

  // Pure dark base — no full-coverage colored bg. Just a near-black with a
  // very faint radial breath so the canvas isn't dead-flat.
  float r = length(p);
  vec3 col = vec3(0.012, 0.012, 0.018) +
             vec3(0.020, 0.018, 0.030) * (1.0 - smoothstep(0.0, 0.9, r)) * (0.6 + uSwell * 0.6);

  // Add geometric accents (additive blend over black)
  col += accents(pAccents, uTime);

  // Trail ghost (slightly behind, faded) — gives motion a smear.
  // Skipped during the OIIA spin pose because the blob already provides motion blur.
  if (uTrail.z > 0.001 && uPose != 2) {
    vec4 trail = sampleCat(uMeowA, pCat, uTrail.xy, uTrail.w, uRot * 0.92, uShear * 0.6);
    vec3 tinted = trail.rgb * (0.7 + uHigh * 0.5);
    col = mix(col, tinted, trail.a * uTrail.z * 0.55);
  }

  // Crossfade outgoing cat (during pose change).
  // Outgoing always uses the regular sampler — pose change means we're leaving spin behind.
  if (uBlend < 0.999) {
    vec4 prev = sampleCat(uMeowB, pCat, uPos, uScl, uRot, uShear);
    col = mix(col, prev.rgb, prev.a * (1.0 - uBlend));
  }

  // Active cat (the focus). Stand pose uses the OIIA spin sampler.
  vec4 cat = (uPose == 2)
    ? sampleCatSpin(uMeowA, pCat, uPos, uScl, uSpinPhase, uTime)
    : sampleCat    (uMeowA, pCat, uPos, uScl, uRot,       uShear);
  // Beat-synced rim halo around the cat
  float halo = smoothstep(uScl * 1.05, uScl * 0.62, distance(pCat, uPos));
  vec3 haloCol = mix(vec3(0.6, 0.8, 1.0), vec3(1.0, 0.7, 0.9), uBeat);
  col += haloCol * halo * (0.10 + uPulse * 0.20 + uImpact * 0.18);
  // Subtle beat tint on the cat for liveliness
  vec3 catTint = mix(cat.rgb, cat.rgb * (1.10 + uBeat * 0.3), uBeat);
  col = mix(col, catTint, cat.a * uBlend);

  // Soft outer vignette (gentle, doesn't add a "box" feel)
  col *= 1.0 - smoothstep(1.05, 1.55, r) * 0.4;

  gl_FragColor = vec4(col, 1.0);
}
`;
