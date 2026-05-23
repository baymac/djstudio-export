// Sit pose — front-facing symmetric view. Wide haunches, narrower chest,
// centered head with ears, two front legs + paws, tail down right side.
// Matches the TouchDesigner reference design exactly.
export default `
float catSit(vec2 p) {
  // Bigger chest breathe — visibly inhales/exhales
  float breathe = sin(uTime * 1.10) * 0.014;
  float s = uPulse;

  // Lower haunches — wide rounded base
  float haunches = sdRoundBox(p - vec2(0.0, -0.105) * s,
                               vec2(0.160, 0.100 + breathe * 0.5) * s, 0.064 * s);
  // Chest expands and contracts visibly
  float chest = sdRoundBox(p - vec2(0.0, 0.080 + breathe * 0.5) * s,
                             vec2(0.118 + breathe * 1.4, 0.094 + breathe * 0.6) * s, 0.054 * s);
  float body = opSU(haunches, chest, 0.055 * s);

  // Neck connecting body to head — slight head bob with breath
  float headBob = sin(uTime * 1.10) * 0.006;
  float neck = sdCapsule(p, vec2(0.0, 0.170) * s, vec2(0.0, 0.238 + headBob) * s, 0.046 * s);

  // Head — gentle curiosity tilt fed by uHeadTilt (mid-frequency music)
  float tiltAmt = uHeadTilt * 0.25 + sin(uTime * 0.42) * 0.05;
  vec2  hcRaw = vec2(0.0, 0.318 + headBob) * s;
  vec2  pHead = rot2(p - hcRaw, tiltAmt);
  float head  = sdCircle(pHead, 0.115 * s);
  float snout = sdRoundBox(pHead - vec2(0.0, -0.068) * s, vec2(0.034, 0.024) * s, 0.013 * s);

  // Ears — twitch independently. Left ear flicks more often
  float earTwitchL = (mod(uTime, 3.7) < 0.20) ? sin(mod(uTime, 3.7) * 30.0) * 0.22 : 0.0;
  float earTwitchR = (mod(uTime + 1.8, 5.2) < 0.20) ? sin(mod(uTime + 1.8, 5.2) * 30.0) * 0.20 : 0.0;
  vec2  pEarL = rot2(pHead - vec2(-0.072, 0.094) * s,  0.20 + earTwitchL);
  float earL  = sdRoundBox(pEarL, vec2(0.028, 0.055) * s, 0.010 * s);
  vec2  pEarR = rot2(pHead - vec2( 0.072, 0.094) * s, -0.20 - earTwitchR);
  float earR  = sdRoundBox(pEarR, vec2(0.028, 0.055) * s, 0.010 * s);

  // Front legs — right paw lifts every ~6s like a slow groom
  float groomCycle = mod(uTime, 6.0);
  float pawLift    = (groomCycle < 1.2) ? sin(groomCycle * 2.62) * 0.038 : 0.0;
  float legL = sdCapsule(p, vec2(-0.055,  0.025) * s, vec2(-0.055, -0.236) * s, 0.028 * s);
  float legR = sdCapsule(p, vec2( 0.055,  0.025) * s, vec2( 0.055, -0.236 + pawLift) * s, 0.028 * s);
  float pawL = sdRoundBox(p - vec2(-0.055, -0.254) * s, vec2(0.050, 0.018) * s, 0.012 * s);
  float pawR = sdRoundBox(p - vec2( 0.055, -0.254 + pawLift) * s, vec2(0.050, 0.018) * s, 0.012 * s);

  // Tail — bigger swish, tip flicks faster on high-energy music
  float swishBase = sin(uTime * 0.65) * (0.022 + uTailSwish * 0.030);
  float tipFlick  = sin(uTime * 1.8 + 0.4) * 0.020 * uTailSwish;
  vec2  tRoot = vec2( 0.184, -0.070) * s;
  vec2  tMid  = vec2( 0.218 + swishBase * 0.6, -0.182) * s;
  vec2  tTip  = vec2( 0.196 + swishBase + tipFlick, -0.264) * s;
  float tail  = opU(sdCapsule(p, tRoot, tMid, 0.024 * s),
                     sdCapsule(p, tMid,  tTip, 0.017 * s));

  float d = body;
  d = opSU(d, neck,  0.035 * s);
  d = opSU(d, head,  0.038 * s);
  d = opSU(d, snout, 0.018 * s);
  d = opU(d,  earL); d = opU(d,  earR);
  d = opSU(d, legL,  0.030 * s); d = opSU(d, legR,  0.030 * s);
  d = opSU(d, pawL,  0.020 * s); d = opSU(d, pawR,  0.020 * s);
  d = opSU(d, tail,  0.020 * s);
  return d;
}
`;
