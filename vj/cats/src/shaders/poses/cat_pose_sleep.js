// Sleep pose — loaf position, slow breathing, head raised at right.
export default `
float catSleep(vec2 p) {
  // Slow purr breathe — bigger amplitude than realistic, sells the "asleep but alive" feel
  float breathe = 1.0 + sin(uTime * 0.55) * 0.030;
  float s = breathe * uPulse;

  // Body subtly rises and falls with each breath
  float bodyY = -0.030 + sin(uTime * 0.55) * 0.008;
  float body  = sdRoundBox(p - vec2(0.0, bodyY) * s, vec2(0.200, 0.088) * s, 0.072 * s);

  // Head bobs gently with breath
  float headBob = sin(uTime * 0.55) * 0.006;
  vec2  hc    = vec2(0.162, 0.118 + headBob) * s;
  float head  = sdCircle(p - hc, 0.098 * s);
  float snout = sdRoundBox(p - hc - vec2(0.090, -0.006) * s, vec2(0.032, 0.022) * s, 0.012 * s);

  // Ear twitch — sharp impulse every few seconds (mod-based)
  float twitchCycle = mod(uTime, 4.5);
  float earTwitch   = (twitchCycle < 0.25) ? sin(twitchCycle * 25.0) * 0.18 : 0.0;
  vec2  earBP = rot2(p - (hc + vec2(-0.040, 0.108) * s),  0.18 + earTwitch);
  float earB  = sdRoundBox(earBP, vec2(0.020, 0.048) * s, 0.010 * s);
  vec2  earFP = rot2(p - (hc + vec2( 0.044, 0.104) * s), -0.18 - earTwitch * 0.7);
  float earF  = sdRoundBox(earFP, vec2(0.020, 0.048) * s, 0.010 * s);

  // Single long front leg stretching right
  vec2  fRootL = vec2( 0.148, -0.096) * s;
  vec2  fPawLC = vec2( 0.348, -0.124) * s;
  float fLegL  = sdCapsule(p, fRootL, fPawLC, 0.028 * s);
  float fPawL  = sdCircle(p - fPawLC, 0.040 * s);

  // Hind leg stubs
  vec2  hPawLC = vec2(-0.148, -0.128) * s;
  vec2  hPawRC = vec2(-0.192, -0.124) * s;
  float hLegL  = sdCapsule(p, vec2(-0.130, -0.105) * s, hPawLC, 0.025 * s);
  float hLegR  = sdCapsule(p, vec2(-0.172, -0.102) * s, hPawRC, 0.025 * s);
  float hPawL  = sdCircle(p - hPawLC, 0.030 * s);
  float hPawR  = sdCircle(p - hPawRC, 0.028 * s);

  // Tail: slow base sway plus a faster tip-flick (the giveaway that she's not deep asleep)
  float ts      = sin(uTime * 0.42) * 0.22;
  float tipFlip = sin(uTime * 1.4 + 0.7) * 0.040 * uTailSwish;
  vec2  tR   = vec2(-0.188, -0.068) * s;
  vec2  tM   = tR + vec2(-0.025,  0.112 + sin(ts) * 0.030) * s;
  vec2  tT   = tM + vec2( 0.062 + tipFlip,  0.076 + cos(ts + 1.0) * 0.026) * s;
  float tail = opU(sdCapsule(p, tR, tM, 0.030 * s), sdCapsule(p, tM, tT, 0.022 * s));

  float d = opSU(body, head, 0.022 * s);
  d = opSU(d, snout, 0.013 * s);
  d = opU(d, earB);  d = opU(d, earF);
  d = opSU(d, fLegL, 0.018 * s); d = opU(d, fPawL);
  d = opSU(d, hLegL, 0.015 * s); d = opU(d, hPawL);
  d = opSU(d, hLegR, 0.015 * s); d = opU(d, hPawR);
  d = opU(d, tail);
  return d;
}
`;
