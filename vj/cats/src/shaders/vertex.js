// Shared vertex shader — used by every scene.
// p5.js gives us aPosition in [0,1] for a fullscreen rect; we map to clip space.
export default `
attribute vec3 aPosition;
attribute vec2 aTexCoord;
void main() {
  vec4 p = vec4(aPosition, 1.0);
  p.xy = p.xy * 2.0 - 1.0;
  gl_Position = p;
}
`;
