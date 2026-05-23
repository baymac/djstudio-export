// Cobra / stretch pose — body diagonal high-rear to low-front, paws
// stretched forward along the ground, tail sweeping up from raised hips.
// Reference: cat prayer stretch / extended puppy pose.
export default `
float yogaCobra(vec2 p, float s) {
  // Hips rise and fall — sells the stretch
  float hipLift = sin(uTime * 0.55) * 0.022;
  // Head dips down and back up — the prayer-stretch motion
  float headDip = sin(uTime * 0.55 + 1.2) * 0.018;

  // Body: angled from elevated rear (left) down to front chest (right)
  vec2  rearHips   = vec2(-0.178,  0.055 + hipLift) * s;
  vec2  frontChest = vec2( 0.068, -0.044) * s;
  float body = sdCapsule(p, rearHips, frontChest, 0.086 * s);

  // Head: at front, low — dips with breath
  vec2  hc    = vec2( 0.218, -0.006 + headDip) * s;
  float head  = sdCircle(p - hc, 0.095 * s);
  float snout = sdRoundBox(p - hc - vec2(0.082, -0.004) * s, vec2(0.030, 0.020) * s, 0.012 * s);
  float earB  = sdRoundBox(rot2(p - hc - vec2(-0.022,  0.080) * s,  0.20), vec2(0.016, 0.034) * s, 0.008 * s);
  float earF  = sdRoundBox(rot2(p - hc - vec2( 0.058,  0.076) * s, -0.20), vec2(0.016, 0.034) * s, 0.008 * s);

  // Front legs: stretching far forward and low (prayer stretch)
  float lw  = 0.024 * s;
  float fl1 = sdCapsule(p, vec2( 0.132, -0.060) * s, vec2( 0.318, -0.150) * s, lw);
  float fl2 = sdCapsule(p, vec2( 0.084, -0.058) * s, vec2( 0.270, -0.150) * s, lw);
  float fp1 = sdCircle(p - vec2( 0.326, -0.164) * s, 0.024 * s);
  float fp2 = sdCircle(p - vec2( 0.276, -0.164) * s, 0.024 * s);

  // Rear legs: down from the raised hips
  float rl1 = sdCapsule(p, rearHips + vec2( 0.022, -0.020) * s, rearHips + vec2( 0.026, -0.192) * s, lw);
  float rl2 = sdCapsule(p, rearHips + vec2(-0.024, -0.020) * s, rearHips + vec2(-0.018, -0.192) * s, lw);

  // Tail sweeps up dramatically — bigger sweep, audio-reactive tip
  float ts   = sin(uTime * 0.85) * (0.32 + uTailSwish * 0.25);
  vec2  tR   = rearHips + vec2(-0.006, 0.012) * s;
  vec2  tM   = tR + vec2(-0.020 + sin(ts) * 0.058,  0.188) * s;
  vec2  tT   = tM + vec2( 0.008 + cos(ts + 1.0) * 0.044,  0.130) * s;
  float tail = opU(sdCapsule(p, tR, tM, 0.030 * s), sdCapsule(p, tM, tT, 0.022 * s));

  float d = opSU(body, head, 0.048 * s);
  d = opSU(d, snout, 0.016 * s);
  d = opU(d, earB); d = opU(d, earF); d = opU(d, tail);
  d = opSU(d, fl1, 0.015 * s); d = opSU(d, fl2, 0.015 * s);
  d = opU(d, fp1);  d = opU(d, fp2);
  d = opSU(d, rl1, 0.014 * s); d = opSU(d, rl2, 0.014 * s);
  return d;
}
`;
