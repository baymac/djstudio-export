// Pose Blender — smoothly transitions between cat poses.
// Timing is driven externally by deck.js; this module only handles blending
// and audio-reactive uniforms.
export function createState() {

  let currentPose = 'sleep';

  // Each pose belongs to one of Shweta's cats:
  //   Mewtwo (orange) — the active poses (sit, cobra, run)
  //   Chewtwo (grey)  — the calmer poses (sleep, yoga, stand/spin)
  //   Duet            — both cats appear together; shader handles per-cat color
  const MEWTWO = [1.00, 0.58, 0.18];
  const CHEWTWO = [0.74, 0.76, 0.82];
  const POSE_COLORS = {
    sleep: CHEWTWO,
    sit: MEWTWO,
    yoga: CHEWTWO,
    cobra: MEWTWO,
    run: MEWTWO,
    spin: CHEWTWO,
    duet: MEWTWO,
  };

  const poseWeights = { run: 0, sit: 0, sleep: 1, yoga: 0, cobra: 0, spin: 0, duet: 0 };

  const POSE_PRESETS = {
    sleep: { run: 0, sit: 0, sleep: 1, yoga: 0, cobra: 0, spin: 0, duet: 0 },
    sit: { run: 0, sit: 1, sleep: 0, yoga: 0, cobra: 0, spin: 0, duet: 0 },
    yoga: { run: 0, sit: 0, sleep: 0, yoga: 1, cobra: 0, spin: 0, duet: 0 },
    cobra: { run: 0, sit: 0, sleep: 0, yoga: 0, cobra: 1, spin: 0, duet: 0 },
    run: { run: 1, sit: 0, sleep: 0, yoga: 0, cobra: 0, spin: 0, duet: 0 },
    spin: { run: 0, sit: 0, sleep: 0, yoga: 0, cobra: 0, spin: 1, duet: 0 },
    duet: { run: 0, sit: 0, sleep: 0, yoga: 0, cobra: 0, spin: 0, duet: 1 },
  };

  let lerpWake = 1.8;
  let lerpSleep = 0.7;
  let poseTime = 0;

  const uniforms = {
    uSpeed: 0, uJump: 0, uPulse: 1, uEnergy: 0,
    uYaw: 0, uPitch: 0, uRoll: 0,
    uBeat: 0, uImpact: 0, uSwell: 0,
    uLow: 0, uMid: 0, uHigh: 0,
    uPoseRun: 0, uPoseSit: 0, uPoseSleep: 1, uPoseYoga: 0,
    uPoseCobra: 0, uPoseSpin: 0, uPoseDuet: 0,
    uHeadTilt: 0, uTailSwish: 0.4,
    uPoseTime: 0,
    uCatColor: CHEWTWO.slice(),
  };

  let yaw = 0, pitch = 0, roll = 0;

  // setPose(pose, snap?) — when snap is true, pose weights are set immediately
  // to the new pose's preset (no blend). Use snap when entering the cat
  // section from a non-cat section so the first cat scene renders correctly
  // from frame 1 instead of visibly morphing in from the previous pose.
  function setPose(pose, snap = false) {
    if (currentPose === pose && !snap) return;
    currentPose = pose;
    poseTime = 0;
    lerpWake = 1.4 + Math.random() * 1.2;
    lerpSleep = 0.5 + Math.random() * 0.6;
    uniforms.uCatColor = (POSE_COLORS[pose] || MEWTWO).slice();
    if (snap) {
      const preset = POSE_PRESETS[pose] || POSE_PRESETS.sleep;
      for (const k in poseWeights) poseWeights[k] = preset[k];
      // Reflect snapped weights immediately in the uniforms so the first
      // rendered frame already shows the right pose.
      uniforms.uPoseRun   = poseWeights.run;
      uniforms.uPoseSit   = poseWeights.sit;
      uniforms.uPoseSleep = poseWeights.sleep;
      uniforms.uPoseYoga  = poseWeights.yoga;
      uniforms.uPoseCobra = poseWeights.cobra;
      uniforms.uPoseSpin  = poseWeights.spin;
      uniforms.uPoseDuet  = poseWeights.duet;
    }
  }

  function update(f, dt) {
    poseTime += dt;
    uniforms.uPoseTime = poseTime;

    const activePose = f.hasAudio ? currentPose : 'sleep';
    const preset = POSE_PRESETS[activePose];
    for (const k in poseWeights) {
      const up = preset[k] > poseWeights[k];
      poseWeights[k] += (preset[k] - poseWeights[k]) * Math.min(1, dt * (up ? lerpWake : lerpSleep));
    }

    const low = clamp01(f.low || f.bass);
    const mid = clamp01(f.mid);
    const high = clamp01(f.high);
    const beat = clamp01(f.pulse || f.beat);
    const impact = clamp01(f.impact);
    const swell = clamp01(f.swell || f.energy);

    const speedTarget = f.hasAudio ? 0.8 + swell * 6.8 + low * 2.2 + beat * 0.9 : 0;
    uniforms.uSpeed = lerp(uniforms.uSpeed, speedTarget, 0.06);
    uniforms.uJump = beat * (0.10 + low * 0.16) + impact * 0.05;
    uniforms.uPulse = 1.0 + low * 0.18 + beat * 0.14 + swell * 0.08;
    uniforms.uEnergy = f.energy;
    uniforms.uBeat = beat;
    uniforms.uImpact = impact;
    uniforms.uSwell = swell;
    uniforms.uLow = low;
    uniforms.uMid = mid;
    uniforms.uHigh = high;

    yaw += dt * (0.16 + high * 1.2 + clamp01(f.hihatDensity) * 0.8 + beat * 0.5);
    pitch = lerp(pitch, low * 0.16 + beat * 0.04 - high * 0.03, 0.08);
    roll = lerp(roll, Math.sin(performance.now() * 0.0012) * (0.03 + swell * 0.10) + (high - low) * 0.05, 0.05);

    uniforms.uYaw = yaw;
    uniforms.uPitch = pitch;
    uniforms.uRoll = roll;

    uniforms.uPoseRun = poseWeights.run;
    uniforms.uPoseSit = poseWeights.sit;
    uniforms.uPoseSleep = poseWeights.sleep;
    uniforms.uPoseYoga = poseWeights.yoga;
    uniforms.uPoseCobra = poseWeights.cobra;
    uniforms.uPoseSpin = poseWeights.spin;
    uniforms.uPoseDuet = poseWeights.duet;

    uniforms.uTailSwish = 0.24 + poseWeights.run * 0.65 + high * 0.42 + impact * 0.28;
    uniforms.uHeadTilt = Math.sin(performance.now() * 0.0008) * mid * 0.65 + impact * 0.06;
  }

  function lerp(a, b, t) { return a + (b - a) * t; }
  function clamp01(v) { return Math.max(0, Math.min(1, v || 0)); }

  // Reset all pose blending + audio-reactive uniforms back to defaults.
  // Called when the show is interrupted by silence so the next music-on
  // event starts from a clean slate instead of resuming mid-animation.
  function reset() {
    currentPose = 'sleep';
    poseTime    = 0;
    lerpWake    = 1.8;
    lerpSleep   = 0.7;
    const preset = POSE_PRESETS.sleep;
    for (const k in poseWeights) poseWeights[k] = preset[k];
    yaw = 0; pitch = 0; roll = 0;
    uniforms.uSpeed = 0; uniforms.uJump = 0; uniforms.uPulse = 1; uniforms.uEnergy = 0;
    uniforms.uYaw = 0; uniforms.uPitch = 0; uniforms.uRoll = 0;
    uniforms.uBeat = 0; uniforms.uImpact = 0; uniforms.uSwell = 0;
    uniforms.uLow = 0; uniforms.uMid = 0; uniforms.uHigh = 0;
    uniforms.uPoseRun = 0; uniforms.uPoseSit = 0; uniforms.uPoseSleep = 1; uniforms.uPoseYoga = 0;
    uniforms.uPoseCobra = 0; uniforms.uPoseSpin = 0; uniforms.uPoseDuet = 0;
    uniforms.uHeadTilt = 0; uniforms.uTailSwish = 0.4;
    uniforms.uPoseTime = 0;
    uniforms.uCatColor = CHEWTWO.slice();
  }

  return {
    update, setPose, reset,
    uniforms,
    get label() { return currentPose.toUpperCase(); },
  };
}
