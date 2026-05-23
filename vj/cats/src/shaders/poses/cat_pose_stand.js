// Front-facing standing cat.
// Animations: gentle breathe, wide tail arc, jump squash-stretch on beat.
export default `
float catStand(vec2 p) {
  // Bigger breathe + a constant idle bounce so she's never frozen
  float breathe   = 1.0 + sin(uTime * 0.60) * 0.034;
  float idleBob   = sin(uTime * 1.6) * 0.012 * (0.6 + uEnergy * 1.4);
  // Audio-reactive bounce on the beat
  p.y -= idleBob;
  float s = uPulse * breathe;

  // Jump squash-stretch: body stretches tall, squashes wide on beat.
  float j        = uJump;
  float jStretch = 1.0 + j * 0.85;
  float jSquash  = 1.0 - j * 0.50;
  vec2  pJ = vec2(p.x / jSquash, p.y / jStretch);

  // Body
  float body = sdRoundBox(pJ - vec2(0.0, 0.002) * s, vec2(0.178, 0.114) * s, 0.076 * s);

  // Head with subtle vertical bob
  float headBob = sin(uTime * 0.55) * 0.006;
  vec2  hc   = vec2(0.0, 0.200 + headBob) * s;
  float head = sdCircle(pJ - hc, 0.120 * s);
  float neck = sdCapsule(pJ, vec2(0.0, 0.116) * s, vec2(0.0, 0.182 + headBob) * s, 0.052 * s);
  float snout = sdRoundBox(pJ - hc - vec2(0.0, -0.055) * s, vec2(0.040, 0.028) * s, 0.016 * s);

  // Ears twitch on different cycles — alive and reactive
  float earTwL = (mod(uTime, 4.1) < 0.18) ? sin(mod(uTime, 4.1) * 32.0) * 0.18 : 0.0;
  float earTwR = (mod(uTime + 2.3, 5.7) < 0.18) ? sin(mod(uTime + 2.3, 5.7) * 32.0) * 0.18 : 0.0;
  vec2  pEarL = rot2(pJ - hc - vec2(-0.082, 0.104) * s,  0.14 + earTwL);
  float earL  = sdRoundBox(pEarL, vec2(0.024, 0.052) * s, 0.009 * s);
  vec2  pEarR = rot2(pJ - hc - vec2( 0.082, 0.104) * s, -0.14 - earTwR);
  float earR  = sdRoundBox(pEarR, vec2(0.024, 0.052) * s, 0.009 * s);

  float legFL = sdCapsule(pJ, vec2(-0.068, -0.088) * s, vec2(-0.068, -0.218) * s, 0.028 * s);
  float legFR = sdCapsule(pJ, vec2( 0.068, -0.088) * s, vec2( 0.068, -0.218) * s, 0.028 * s);
  float legBL = sdCapsule(pJ, vec2(-0.150, -0.058) * s, vec2(-0.150, -0.206) * s, 0.026 * s);
  float legBR = sdCapsule(pJ, vec2( 0.150, -0.058) * s, vec2( 0.150, -0.206) * s, 0.026 * s);
  float pawFL = sdCircle(pJ - vec2(-0.068, -0.236) * s, 0.034 * s);
  float pawFR = sdCircle(pJ - vec2( 0.068, -0.236) * s, 0.034 * s);
  float pawBL = sdCircle(pJ - vec2(-0.152, -0.222) * s, 0.030 * s);
  float pawBR = sdCircle(pJ - vec2( 0.152, -0.222) * s, 0.030 * s);

  // Tail: two-joint arc, uses un-squashed p so it swings freely
  float tailT = uTime * 0.38;
  float swing = 0.55 + uTailSwish * 0.35;
  float ang1  = 0.80 + sin(tailT) * swing;
  float ang2  = ang1 + 0.45 + sin(tailT * 1.3 + 1.1) * 0.30;
  vec2  tRoot = vec2( 0.185,  0.010) * s;
  vec2  tMid  = tRoot + vec2(cos(ang1), sin(ang1)) * 0.105 * s;
  vec2  tTip  = tMid  + vec2(cos(ang2), sin(ang2)) * 0.088 * s;
  float tail  = opU(sdCapsule(p, tRoot, tMid, 0.024 * s),
                    sdCapsule(p, tMid,  tTip, 0.016 * s));

  float d = body;
  d = opSU(d, neck,  0.038 * s);
  d = opSU(d, head,  0.032 * s);
  d = opSU(d, snout, 0.018 * s);
  d = opU(d, earL); d = opU(d, earR);
  d = opSU(d, legFL, 0.022 * s); d = opSU(d, legFR, 0.022 * s);
  d = opSU(d, legBL, 0.018 * s); d = opSU(d, legBR, 0.018 * s);
  d = opSU(d, pawFL, 0.016 * s); d = opSU(d, pawFR, 0.016 * s);
  d = opSU(d, pawBL, 0.014 * s); d = opSU(d, pawBR, 0.014 * s);
  d = opU(d, tail);
  return d;
}
`;
