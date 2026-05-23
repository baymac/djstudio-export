// Yoga Cat pose — actual cat yoga flow.
// Cycles between Cat (Marjaryasana, spine up + head tucked) and Cow/Cobra (spine
// sagged + head lifted). Plus head-turn glances, periodic pounce, breath-synced
// flex. Smoothstep biases time toward holding the extreme poses.
export default `
float yogaCat(vec2 p, float s) {
  // ── Cat-Cow phase ──────────────────────────────────────────────────────
  // ~7s period. Smoothstep narrows the transition window so the cat lingers
  // at each extreme rather than constantly oscillating.
  float ccPhase = sin(uTime * 0.90);                 // -1 (cow) → +1 (cat)
  float ccS     = smoothstep(-0.35, 0.35, ccPhase);  // 0 = cow, 1 = cat (with hold)

  // Breath flex syncs with the phase — peak inhale at cow, exhale at cat
  float breathFlex = sin(uTime * 0.90) * 0.022;

  // ── Periodic pounce — every ~13 s the cat does a small playful jump ─────
  float pounceT = mod(uTime, 13.0);
  float pounceY = (pounceT < 1.0) ? sin(pounceT * 3.14159) * 0.060 : 0.0;
  p.y -= pounceY;

  // ── Hip sway — gentle weight shift independent of the cat-cow cycle ────
  float hipSway = sin(uTime * 0.42) * 0.012;

  // ── Spine geometry — interpolate between cat (arch up) and cow (sag) ───
  vec2  fbCat = vec2( 0.175, -0.018);  vec2 fbCow = vec2( 0.178,  0.022);
  vec2  apCat = vec2( 0.000,  0.230);  vec2 apCow = vec2( 0.000, -0.038);
  vec2  rbCat = vec2(-0.175, -0.018);  vec2 rbCow = vec2(-0.182,  0.020);

  vec2  frontBase = (mix(fbCow, fbCat, ccS) + vec2(hipSway, 0.0)) * s;
  vec2  archPeak  = (mix(apCow, apCat, ccS) + vec2(0.0, breathFlex)) * s;
  vec2  rearBase  = (mix(rbCow, rbCat, ccS) + vec2(hipSway, 0.0)) * s;
  float bodyF = sdCapsule(p, frontBase, archPeak, 0.082 * s);
  float bodyR = sdCapsule(p, archPeak,  rearBase, 0.078 * s);
  float body  = opSU(bodyF, bodyR, 0.042 * s);

  // ── Head — cat tucks chin down, cow lifts head up ──────────────────────
  vec2  hcCat = vec2( 0.262, -0.062);
  vec2  hcCow = vec2( 0.290,  0.110);
  vec2  hc    = mix(hcCow, hcCat, ccS) * s;

  // Head-turn glance — slight side-to-side yaw + tilt on a different cycle
  float headTurn = sin(uTime * 0.55);
  vec2  hcOff    = vec2(headTurn * 0.014, 0.0) * s;
  float headTilt = headTurn * 0.13;
  vec2  pH    = rot2(p - (hc + hcOff), headTilt);

  float head  = sdCircle(pH, 0.096 * s);

  // Snout direction tracks the cat-cow blend — points down in cat, up in cow
  vec2  snCat = vec2(0.074, -0.050);
  vec2  snCow = vec2(0.082,  0.030);
  vec2  snOff = mix(snCow, snCat, ccS);
  float snout = sdRoundBox(pH - snOff * s, vec2(0.033, 0.022) * s, 0.013 * s);

  // Ears — rotate with head, perk a bit more in cow (alert, head-up posture)
  float earTilt = mix(0.28, 0.20, ccS);
  float earB    = sdRoundBox(rot2(pH - vec2(-0.024,  0.086) * s,  earTilt), vec2(0.016, 0.036) * s, 0.008 * s);
  float earF    = sdRoundBox(rot2(pH - vec2( 0.063,  0.082) * s, -earTilt), vec2(0.016, 0.036) * s, 0.008 * s);

  // ── Legs ───────────────────────────────────────────────────────────────
  float lw   = 0.025 * s;
  float legH = mix(0.142, 0.158, ccS) * s; // slightly shorter when cow (paws planted)
  float fl1 = sdCapsule(p, frontBase + vec2( 0.028, 0.0) * s, frontBase + vec2( 0.028, -legH), lw);
  float fl2 = sdCapsule(p, frontBase + vec2(-0.036, 0.0) * s, frontBase + vec2(-0.036, -legH), lw);
  float rl1 = sdCapsule(p, rearBase  + vec2( 0.036, 0.0) * s, rearBase  + vec2( 0.036, -legH), lw);
  float rl2 = sdCapsule(p, rearBase  + vec2(-0.028, 0.0) * s, rearBase  + vec2(-0.028, -legH), lw);

  // ── Tail — high arch in cat, lower swish in cow ────────────────────────
  float tailLift = mix(0.04, 0.18, ccS);
  float ts       = sin(uTime * 0.85) * (0.32 + uTailSwish * 0.30);
  vec2  tR   = rearBase + vec2(0.0, tailLift) * s;
  vec2  tM   = tR + vec2(-0.018 + sin(ts) * 0.058,  0.185) * s;
  vec2  tT   = tM + vec2( 0.008 + cos(ts + 1.0) * 0.046, 0.135) * s;
  float tail = opU(sdCapsule(p, tR, tM, 0.030 * s), sdCapsule(p, tM, tT, 0.022 * s));

  float d = opSU(body, head, 0.042 * s);
  d = opSU(d, snout, 0.016 * s);
  d = opU(d, earB); d = opU(d, earF); d = opU(d, tail);
  d = opU(d, fl1);  d = opU(d, fl2);
  d = opU(d, rl1);  d = opU(d, rl2);
  return d;
}
`;
