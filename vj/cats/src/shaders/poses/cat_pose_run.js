// Run pose — side view, speed-driven gait progression.
// uSpeed 0-1: barely moving / stand
// uSpeed 1-3: walk (slow deliberate steps)
// uSpeed 3-5: trot/run (diagonal pairs)
// uSpeed 5-7: fast run (gallop, body stretches)
// uSpeed 7+:  very fast run (max stretch, low lean)
export default `
float catRun(vec2 p) {
  float spd = max(0.0, uSpeed);

  // Pose timeline: long walk first, brief speed-up to run, very brief fast/very-fast.
  // pow(.., 2.4) holds the curve near zero for ~half the time, then ramps up sharply.
  // At pose dwell of 16-32 s, ramp completes around 22 s — so most of the dwell is walk
  // territory and only the tail end lands in fast-run.
  float poseProgress = clamp(uPoseTime / 22.0, 0.0, 1.0);
  float poseRamp     = pow(poseProgress, 2.4);

  // Effective speed: starts at a leisurely walking floor, eases up to the music-driven
  // value as the pose plays out. Audio energy still controls the ceiling.
  float effSpd = mix(0.4, spd, poseRamp);

  // Gait shape parameters now follow effective speed, not raw audio speed.
  float t   = smoothstep(0.0, 9.0, effSpd);   // 0=walk, 1=full gallop
  float tHi = smoothstep(4.5, 9.0, effSpd);   // ramps at fast run

  // Cycle frequency: also ramps with effective speed, with a floor so legs always move
  float cycleSpd = max(0.5, effSpd);
  float cyc   = uTime * cycleSpd;
  float phase = cyc * 2.0;

  float bobAmp = mix(0.004, 0.024, t);
  float strAmp = mix(0.008, 0.022, t);
  float bob = sin(phase) * bobAmp;
  float str = sin(phase) * strAmp;
  p.y -= bob;

  // Squash-stretch: at top of bob (sin = 1) body stretches taller; at landing (sin = -1)
  // body squashes wider. Amplitude scales with run speed so it reads at gallop.
  float ss       = -sin(phase);                 // -1 at top, +1 at landing
  float ssAmp    = mix(0.05, 0.16, t);          // bigger at fast run
  float runStretch = 1.0 - ss * ssAmp;          // taller at top
  float runSquash  = 1.0 + ss * ssAmp;          // wider at landing

  // Body: elongates and flattens at high speed, squashes/stretches per stride
  float bx   = (mix(0.195, 0.278, t) + str) * uPulse * runSquash;
  float by   =  mix(0.105, 0.078, t) * uPulse * runStretch;
  float body = sdRoundBox(p, vec2(bx, by), 0.055);

  // Head: moves forward and lowers at speed
  vec2  hc    = vec2(mix(0.25, 0.335, t), mix(0.115, 0.072, tHi));
  float head  = sdCircle(p - hc, mix(0.105, 0.092, t) * uPulse);
  // Snout stretches forward
  float snx   = mix(0.085, 0.108, t);
  float sny   = mix(-0.008, -0.018, tHi);
  float snout = sdRoundBox(p - hc - vec2(snx, sny), vec2(0.038, 0.028), 0.018);
  // Ears flatten backward at high speed
  float earLA = mix( 0.22,  0.40, tHi);
  float earFA = mix(-0.22, -0.42, tHi);
  float earB  = sdRoundBox(rot2(p - hc - vec2(-0.030,  0.100),  earLA), vec2(0.020, 0.042), 0.010);
  float earF  = sdRoundBox(rot2(p - hc - vec2( 0.078,  0.108),  earFA), vec2(0.020, 0.042), 0.010);

  // Tail: flies back and flattens at high speed
  float ts   = sin(cyc * mix(0.60, 0.95, t)) * mix(0.35, 0.65, t);
  vec2  tr   = vec2(-0.20, 0.02 + bob * 1.5);
  vec2  tm   = tr + vec2(-0.10, mix(0.14, 0.04, tHi) + sin(ts) * mix(0.05, 0.11, t));
  vec2  tt   = tm + vec2(mix(-0.05, -0.09, tHi), 0.12 + cos(ts + 1.0) * mix(0.04, 0.09, t));
  float tail = opU(sdCapsule(p, tr, tm, 0.038), sdCapsule(p, tm, tt, 0.028));

  // Legs: swing width and lift increase with speed
  float phA = sin(cyc), phB = sin(cyc + 3.14159);
  float lw  = mix(0.031, 0.024, t);
  float sw  = mix(0.058, 0.118, t);
  float lf  = mix(0.028, 0.068, t);
  float liA = max(0.0, phA) * lf, liB = max(0.0, phB) * lf;

  vec2 frR = vec2( 0.14, -0.10 + bob), frK = frR + vec2(phA * sw * 0.45, -0.085),
       frF = frK + vec2(phA * sw * 0.45, -0.090 + liA);
  vec2 flR = vec2( 0.09, -0.10 + bob), flK = flR + vec2(phB * sw * 0.45, -0.085),
       flF = flK + vec2(phB * sw * 0.45, -0.090 + liB);
  vec2 brR = vec2(-0.11, -0.10 + bob), brK = brR + vec2(phB * -sw * 0.55, -0.075),
       brF = brK + vec2(phB * -sw * 0.50, -0.090 + liB);
  vec2 blR = vec2(-0.15, -0.10 + bob), blK = blR + vec2(phA * -sw * 0.55, -0.075),
       blF = blK + vec2(phA * -sw * 0.50, -0.090 + liA);

  float d = opSU(body, head, 0.040);
  d = opSU(d, snout, 0.020);
  d = opU(d, earB); d = opU(d, earF); d = opU(d, tail);
  d = opU(d, opU(sdCapsule(p, frR, frK, lw), sdCapsule(p, frK, frF, lw * 0.78)));
  d = opU(d, opU(sdCapsule(p, flR, flK, lw), sdCapsule(p, flK, flF, lw * 0.78)));
  d = opU(d, opU(sdCapsule(p, brR, brK, lw), sdCapsule(p, brK, brF, lw * 0.78)));
  d = opU(d, opU(sdCapsule(p, blR, blK, lw), sdCapsule(p, blK, blF, lw * 0.78)));
  return d;
}
`;
