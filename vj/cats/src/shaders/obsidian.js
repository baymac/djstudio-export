import helpers from './poses/cat_pose_helpers.js';

export default [
  `precision mediump float;

uniform float uTime;
uniform vec2  uResolution;
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
`,
  helpers,
  `
float hash21(vec2 p) {
  p = fract(p * vec2(234.34, 435.345));
  p += dot(p, p + 34.23);
  return fract(p.x * p.y);
}

float tri(float x) {
  return abs(fract(x) - 0.5);
}

vec2 tunnelPath(float z) {
  return vec2(
    sin(z * 0.65 + uTime * 0.45) * (0.16 + uLow * 0.09),
    cos(z * 0.42 - uTime * 0.32) * (0.10 + uMid * 0.05)
  );
}

float catGlyph(vec2 p) {
  p *= 1.08;
  float body = sdRoundBox(p - vec2(0.0, -0.02), vec2(0.16, 0.12), 0.08);
  float head = sdCircle(p - vec2(0.0, 0.18), 0.11);
  float earL = sdRoundBox(rot2(p - vec2(-0.08, 0.28), 0.16), vec2(0.022, 0.052), 0.010);
  float earR = sdRoundBox(rot2(p - vec2( 0.08, 0.28),-0.16), vec2(0.022, 0.052), 0.010);
  float legL = sdCapsule(p, vec2(-0.07, -0.08), vec2(-0.07, -0.23), 0.028);
  float legR = sdCapsule(p, vec2( 0.07, -0.08), vec2( 0.07, -0.23), 0.028);
  float pawL = sdCircle(p - vec2(-0.07, -0.25), 0.03);
  float pawR = sdCircle(p - vec2( 0.07, -0.25), 0.03);
  float tail = sdCapsule(
    p,
    vec2(0.16, 0.02),
    vec2(0.32 + sin(uTime * 0.9 + p.y * 4.0) * 0.03, 0.18),
    0.022
  );

  float d = opSU(body, head, 0.035);
  d = opU(d, earL);
  d = opU(d, earR);
  d = opSU(d, legL, 0.020);
  d = opSU(d, legR, 0.020);
  d = opSU(d, pawL, 0.016);
  d = opSU(d, pawR, 0.016);
  d = opU(d, tail);
  return d;
}

vec3 spectralPalette(float t) {
  vec3 a = vec3(0.05, 0.06, 0.10);
  vec3 b = vec3(0.95, 0.48, 0.16);
  vec3 c = vec3(0.31, 0.57, 0.92);
  return mix(a, b, clamp(t, 0.0, 1.0)) + c * pow(max(t - 0.55, 0.0), 1.8);
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution;
  vec2 p = uv * 2.0 - 1.0;
  p.x *= uResolution.x / uResolution.y;
  p = rot2(p, uRoll * 0.45);
  p.y += uPitch * 0.42;

  float time = uTime * (0.55 + uEnergy * 0.22 + uBeat * 0.15);
  vec3 color = vec3(0.012, 0.012, 0.024);
  float vignette = smoothstep(1.45, 0.18, length(p * vec2(0.88, 1.08)));

  for (int i = 0; i < 32; i++) {
    float fi = float(i);
    float depth = fract(fi / 32.0 + time * 0.10);
    float z = pow(depth, 1.55);
    float scale = mix(3.8, 0.22, z);
    vec2 path = tunnelPath(fi * 0.23 + time * 1.4);
    vec2 q = (p - path) * scale;

    float radius = 0.58 + sin(fi * 0.55 + uTime * 0.9) * 0.07 + uLow * 0.05;
    float ring = abs(length(q) - radius);
    float ringGlow = smoothstep(0.10, 0.0, ring);

    float angle = atan(q.y, q.x);
    float spokes = pow(max(0.0, cos(angle * 6.0 + fi * 0.5 + uYaw * 0.06)), 7.0);
    float wave = sin(q.y * 7.0 - fi * 0.8 + uTime * (1.4 + uMid * 1.8));
    float shard = sdRoundBox(rot2(q - vec2(0.0, wave * 0.03), fi * 0.12 + uTime * 0.20), vec2(0.11, 0.58), 0.07);
    float shardGlow = smoothstep(0.16, -0.02, shard);

    float catLane = mix(-0.48, 0.48, step(0.5, fract(fi * 0.37)));
    vec2 catP = rot2(q - vec2(catLane + sin(fi * 1.3 + uTime) * 0.08, -0.02), sin(fi * 0.9 + uTime * 0.4) * 0.4);
    float cat = catGlyph(catP * 1.55);
    float catMask = smoothstep(0.06, -0.03, cat);
    float catEdge = smoothstep(0.18, 0.0, abs(cat));

    float portal = smoothstep(0.45, 0.0, abs(q.x) * 0.65 + abs(q.y) * 0.92 - (0.44 + tri(fi * 0.19 + uTime * 0.08) * 0.22));
    float haze = smoothstep(1.4, 0.18, length(q)) * (0.08 + uSwell * 0.10);

    vec3 layerCol = spectralPalette(1.0 - z);
    layerCol = mix(layerCol, vec3(0.95, 0.80, 0.58), catMask * 0.55 + uBeat * 0.08);
    layerCol += vec3(0.36, 0.48, 0.92) * spokes * (0.10 + uHigh * 0.14);
    layerCol += vec3(0.92, 0.40, 0.18) * shardGlow * (0.08 + uImpact * 0.20);

    float alpha = ringGlow * (0.05 + z * 0.08);
    alpha += shardGlow * 0.05 * (1.0 - z);
    alpha += catMask * (0.06 + uSwell * 0.06) * (1.0 - z * 0.65);
    alpha += catEdge * 0.04;
    alpha += portal * 0.04;
    alpha += haze * 0.05;

    color += layerCol * alpha;
  }

  float cross = exp(-12.0 * abs(p.x * p.y)) * (0.06 + uImpact * 0.08);
  float ripples = 0.5 + 0.5 * sin(length(p) * (22.0 + uHigh * 10.0) - uTime * (2.6 + uLow * 2.0));
  color += vec3(0.18, 0.24, 0.44) * cross;
  color += vec3(0.16, 0.08, 0.22) * ripples * uSwell * 0.07;
  color *= vignette;
  color = pow(color, vec3(0.9));

  gl_FragColor = vec4(color, 1.0);
}
`,
].join('');
