// Meow Anim — drives transform of the active real-cat photo.
// Each pose has its own motion personality (parametric path + audio reactions).
// Returns a transform packet consumed by scene.js → meow.js shader.
//
// Output (per frame):
//   pose:    0..4 (nap/walk/stand/up/dance)
//   pos:     [x, y]   in p-space (aspect-corrected)
//   scl:     scale
//   rot:     z-rotation
//   shear:   [sx, sy] skew
//   jitter:  glitch displacement amount
//   trail:   { x, y, alpha, scl }   ghost trail packet
//   blend:   crossfade weight 0..1 (0=showing prev, 1=showing current)
//   prevPose:0..4   pose being faded out

const POSE_INDEX = { nap: 0, walk: 1, stand: 2, up: 3, dance: 4 };

const TWO_PI    = Math.PI * 2;
const clamp01   = v => Math.max(0, Math.min(1, v || 0));
const lerp      = (a, b, t) => a + (b - a) * t;
const easeOut   = t => 1 - Math.pow(1 - t, 3);

// Each pose's "base scale" — bigger for stand/up, smaller for nap/walk so the
// motion has room to breathe.
const POSE_BASE_SCALE = [0.42, 0.40, 0.46, 0.48, 0.44];

export function createMeowAnim() {
  let activePose  = 0;
  let prevPose    = 0;
  let blend       = 1;        // 1 = fully on activePose
  let blendSpeed  = 2.5;      // per second

  // Smoothed transform state
  let pos    = [0, 0];
  let scl    = 0.42;
  let rot    = 0;
  let shear  = [0, 0];
  let jitter = 0;

  // Trail (one-frame-delayed ghost — actually integrated lag)
  const trail = { x: 0, y: 0, alpha: 0, scl: 0.42 };

  // Per-pose persistent state (phase accumulators, beat memory, etc.)
  const phase = { walk: 0, stand: 0, up: 0, dance: 0, breath: 0 };
  let beatRecoilT = 0;   // time since last beat-snap
  let beatRecoilA = 0;   // angle added at beat-snap
  let beatRecoilP = [0, 0];
  let impactJitter = 0;

  // Nap pose: occasional dream twitches (random scale/rotation jolts on impact),
  // each decaying exponentially — feels like the cat dreaming about chasing.
  let napTwitchT  = -10;       // last twitch time
  let napTwitchScl = 0;        // current decaying scale offset
  let napTwitchRot = 0;        // current decaying rotation offset

  // Nap pose: motion-pattern mode cycler. The cat is "dreaming" so motion is
  // slow + sleepy, but still visibly geometric — zoom pulses, bobs, drifts.
  //   0 zoom        — scale-pulse "breathing zoom" in/out
  //   1 bob         — slow vertical float up-down
  //   2 drift       — circular drift like floating in space
  //   3 pendulum    — side-to-side rocking with rotation tilt
  let napMode    = 0;
  let napModeT   = 0;          // seconds in current mode
  let napModeDur = 5.0;        // randomized per cycle

  // Walk pose: motion pattern state machine. Cycles through different motion
  // shapes so the cat doesn't just oscillate horizontally forever.
  //   0 horizontal — side-to-side with step-gait bounce
  //   1 vertical   — up-down sweep
  //   2 diagonal   — synced X+Y for diagonal trajectory
  //   3 lissajous  — figure-8 path
  let walkMode      = 0;
  let walkModeT     = 0;            // seconds in current mode
  let walkModeDur   = 4.0;          // randomized per cycle
  let walkDir       = 1;            // ±1 for diagonal direction (randomized)
  // Jump overlay (additive on top of any mode)
  let walkJumpT     = 999;          // time since jump start; >jumpDur = no active jump
  const WALK_JUMP_DUR = 0.55;       // jump arc duration in seconds
  let walkJumpSched = 0;            // time since last attempt
  let walkNextJump  = 1.8;          // seconds until next jump attempt

  // OIIA spin state machine (stand pose).
  // The cat alternates: STILL (crisp) → ramp → FAST (dark blob) → ramp → STILL.
  // Audio shortens still phases on high energy; beats can trigger early spin.
  let spinTargetPhase = 0;   // 0 = still, 1 = fast spin
  let spinPhase       = 0;   // smoothed (the actual visual)
  let spinTimer       = 0;
  let spinStillDur    = 1.4 + Math.random() * 0.8;
  let spinFastDur     = 1.2 + Math.random() * 1.0;

  function setPose(name) {
    const idx = POSE_INDEX[name];
    if (idx === undefined || idx === activePose) return;
    prevPose   = activePose;
    activePose = idx;
    blend      = 0;        // start crossfade
    // Reset the OIIA spin state when entering the stand pose so each
    // visit starts with a still cat for ~1.5 s before the first spin.
    if (idx === 2) {
      spinPhase       = 0;
      spinTargetPhase = 0;
      spinTimer       = 0;
      spinStillDur    = 1.4 + Math.random() * 0.8;
      spinFastDur     = 1.2 + Math.random() * 1.0;
    }
    // Reset walk motion-pattern state on entry so each visit cycles fresh.
    if (idx === 1) {
      walkMode      = 0;
      walkModeT     = 0;
      walkModeDur   = 3.5 + Math.random() * 2.0;
      walkDir       = Math.random() > 0.5 ? 1 : -1;
      walkJumpT     = 999;
      walkJumpSched = 0;
      walkNextJump  = 1.8 + Math.random() * 1.2;
    }
    // Reset nap motion-pattern cycler on entry — fresh sequence each visit.
    if (idx === 0) {
      napMode    = 0;
      napModeT   = 0;
      napModeDur = 4.5 + Math.random() * 3.0;
    }
  }

  function applyTransientReactions(f, dt) {
    // Beat snap: brief spatial recoil + angle pop on each pulse spike.
    if (f.pulse > 0.55 && beatRecoilT > 0.18) {
      beatRecoilT  = 0;
      const r      = (Math.random() * 2 - 1) * 0.06;
      beatRecoilA  = r * 1.4;
      const a      = Math.random() * TWO_PI;
      beatRecoilP  = [Math.cos(a) * 0.04, Math.sin(a) * 0.04];
    }
    beatRecoilT += dt;
    // recoil decays exponentially
    const decay  = Math.pow(0.001, dt * 6.0); // ~6/s
    beatRecoilA *= decay;
    beatRecoilP[0] *= decay;
    beatRecoilP[1] *= decay;

    // Hihat / impact: glitch jitter
    impactJitter = Math.max(impactJitter * Math.pow(0.001, dt * 4.0),
                            (f.hihat || 0) * 0.55 + (f.impact || 0) * 0.35);
  }

  // ── Per-pose motion functions ─────────────────────────────────────────────
  function motionNap(t, f, dt) {
    // ── Advance mode cycler ─────────────────────────────────────────────
    napModeT += dt;
    if (napModeT >= napModeDur) {
      napModeT   = 0;
      napMode    = (napMode + 1) % 4;
      napModeDur = 4.0 + Math.random() * 3.5;
    }

    // Always-on breathing (modulates every mode's scale)
    phase.breath += dt * (0.55 + f.swell * 0.35);
    const breathS = Math.sin(phase.breath);
    const breath  = breathS * 0.5 + 0.5;            // 0..1

    // Dream twitch (cat paws twitching while dreaming; all modes)
    if ((f.impact || 0) > 0.55 && (t - napTwitchT) > 1.5) {
      napTwitchT  = t;
      const r1    = Math.sin(t * 91.7)  * 43758.5453;
      const r2    = Math.sin(t * 137.3) * 43758.5453;
      napTwitchScl = ((r1 - Math.floor(r1)) - 0.5) * 0.10;
      napTwitchRot = ((r2 - Math.floor(r2)) - 0.5) * 0.07;
    }
    const decay = Math.pow(0.001, dt * 4.0);
    napTwitchScl *= decay;
    napTwitchRot *= decay;

    // ── Per-mode motion ─────────────────────────────────────────────────
    let tx = 0, ty = 0.02, trot = 0, tsclMul = 1.0;

    if (napMode === 0) {
      // ── ZOOM IN/OUT: big "breathing" scale pulse + tiny drift
      tx      = Math.sin(t * 0.10) * 0.04;
      ty      = 0.02 + breathS * 0.018;
      tsclMul = 1.0 + breath * 0.18 + f.low * 0.05;   // 1.0..~1.23 — visible zoom
      trot    = Math.sin(t * 0.06) * 0.025;
    } else if (napMode === 1) {
      // ── FLOATING BOB: pronounced slow vertical bob
      tx      = Math.sin(t * 0.18) * 0.06;
      ty      = Math.sin(t * 0.55) * 0.22 + 0.02;     // visible up-down travel
      tsclMul = 1.0 + breath * 0.07;
      trot    = Math.cos(t * 0.55) * 0.05;
    } else if (napMode === 2) {
      // ── DREAM DRIFT: slow circular path
      tx      = Math.sin(t * 0.35) * 0.30;
      ty      = Math.cos(t * 0.35) * 0.20 + 0.02;
      tsclMul = 1.0 + breath * 0.06 + Math.sin(t * 0.7) * 0.04;
      trot    = Math.sin(t * 0.35) * 0.10;            // lean into the drift
    } else {
      // ── PENDULUM SWAY: side-to-side rocking with rotation tilt
      const sw = Math.sin(t * 0.70);
      tx      = sw * 0.28;
      ty      = -Math.abs(sw) * 0.04 + 0.04;          // slight up-bob at swing edges
      tsclMul = 1.0 + breath * 0.06;
      trot    = sw * 0.18;                            // pendulum tilt
    }

    return {
      tx,
      ty,
      tscl:  POSE_BASE_SCALE[0] * (1.0 + f.low * 0.05 + napTwitchScl) * tsclMul,
      trot:  trot + napTwitchRot,
      tshx:  0,
      tshy:  Math.sin(t * 0.13) * 0.025 * f.mid,
    };
  }

  function motionWalk(t, f, dt) {
    // ── Advance mode cycler ─────────────────────────────────────────────
    walkModeT += dt;
    if (walkModeT >= walkModeDur) {
      walkModeT   = 0;
      walkMode    = (walkMode + 1) % 4;
      // Higher energy → shorter modes so patterns change more often
      walkModeDur = (2.8 + Math.random() * 2.4) * Math.max(0.55, 1.0 - f.energy * 0.45);
      walkDir     = Math.random() > 0.5 ? 1 : -1;
    }

    // Shared phase accumulator (audio-reactive speed)
    phase.walk += dt * (0.8 + f.low * 1.6 + f.pulse * 0.4);
    const ph = phase.walk;

    let tx = 0, ty = 0, trot = 0;
    let tsclMul = 1.0;

    if (walkMode === 0) {
      // ── HORIZONTAL: side-to-side with step-gait bounce
      tx   = Math.sin(ph) * 0.55;
      ty   = -Math.abs(Math.sin(ph * 2.0)) * (0.06 + f.low * 0.08) + 0.08;
      trot = Math.cos(ph) * 0.10;
    } else if (walkMode === 1) {
      // ── VERTICAL: up-down sweep with small horizontal drift
      tx   = Math.sin(ph * 0.45) * 0.14;
      ty   = Math.sin(ph) * 0.50;
      trot = Math.cos(ph * 0.5) * 0.07;
    } else if (walkMode === 2) {
      // ── DIAGONAL: synced X+Y for a / or \ trajectory (walkDir flips slope)
      const s = Math.sin(ph);
      tx   = s * 0.50 * walkDir;
      ty   = s * 0.40;            // same phase → diagonal motion
      trot = Math.cos(ph) * 0.10 * walkDir;
    } else {
      // ── LISSAJOUS: figure-8 path
      tx   = Math.sin(ph) * 0.45;
      ty   = Math.sin(ph * 2.0) * 0.35;
      trot = Math.sin(ph * 1.5) * 0.12;
    }

    // ── Jump overlay (additive on top of any mode) ──────────────────────
    walkJumpSched += dt;
    const jumping = walkJumpT < WALK_JUMP_DUR;
    if (!jumping && walkJumpSched >= walkNextJump) {
      // Trigger if there's a strong beat, or 60 % chance otherwise
      if (f.pulse > 0.55 || Math.random() < 0.6) {
        walkJumpT     = 0;
        walkJumpSched = 0;
        walkNextJump  = 1.6 + Math.random() * 2.6;
      } else {
        walkJumpSched -= 0.3; // try again soon
      }
    }
    if (walkJumpT < WALK_JUMP_DUR) {
      walkJumpT += dt;
      const u = walkJumpT / WALK_JUMP_DUR;  // 0..1
      if (u < 1) {
        const arc = Math.sin(u * Math.PI);         // 0 → 1 → 0
        ty      -= arc * 0.32;                      // lifts up (ty is inverted)
        // Tilt forward on ascent, back on descent
        trot    += Math.sin(u * Math.PI * 2.0 - Math.PI * 0.5) * 0.14;
        // Subtle stretch at the peak (cat "puffs up" mid-air)
        tsclMul *= 1.0 + arc * 0.08;
      }
    }

    return {
      tx, ty, trot,
      tscl:  POSE_BASE_SCALE[1] * (1.0 + f.beat * 0.10 + f.low * 0.05) * tsclMul,
      tshx:  0,
      tshy:  0,
    };
  }

  function motionStand(t, f, dt) {
    // ── OIIA spin state machine ─────────────────────────────────────────
    spinTimer += dt;
    const targetDur = spinTargetPhase === 0 ? spinStillDur : spinFastDur;

    // Beat trigger: while still and the still has lasted ≥ 0.6s, a strong
    // beat can kick off an early spin burst.
    if (spinTargetPhase === 0 && spinTimer > 0.6 && f.pulse > 0.55) {
      spinTargetPhase = 1;
      spinTimer       = 0;
      spinFastDur     = 0.9 + Math.random() * 1.5 + f.energy * 0.6;
    } else if (spinTimer >= targetDur) {
      spinTimer = 0;
      spinTargetPhase = 1 - spinTargetPhase;
      if (spinTargetPhase === 1) {
        // Entering fast spin
        spinFastDur = 0.9 + Math.random() * 1.5 + f.energy * 0.5;
      } else {
        // Entering still — shorter still on high energy
        spinStillDur = (1.0 + Math.random() * 1.2) * Math.max(0.4, 1.0 - f.energy * 0.5);
      }
    }

    // Snappy transitions (~80–120 ms) like the OIIA video — cat appears to
    // teleport between still and blur-blob, with just enough ramp to read as
    // motion rather than a hard cut.
    const lerpRate = spinTargetPhase === 1 ? 16.0 : 12.0;
    spinPhase = lerp(spinPhase, spinTargetPhase, Math.min(1, dt * lerpRate));

    // ── Transform ───────────────────────────────────────────────────────
    return {
      tx:    Math.sin(t * 0.30) * 0.020,
      ty:    Math.cos(t * 0.27) * 0.018 - spinPhase * 0.008, // dips slightly when spinning
      tscl:  POSE_BASE_SCALE[2] * (1.0 + f.beat * 0.10 + f.low * 0.05 + spinPhase * 0.04),
      trot:  0,
      tshx:  0,
      tshy:  0,
    };
  }

  function motionUp(t, f, dt) {
    phase.up += dt * (1.2 + f.energy * 1.8 + f.pulse * 0.7);
    // Lissajous figure (asymmetric loop) with energy-scaled radius
    const A    = 0.45 + f.swell * 0.18;
    const B    = 0.30 + f.swell * 0.12;
    const x    = Math.sin(phase.up) * A;
    const y    = Math.sin(phase.up * 2.0 + Math.PI * 0.5) * B + Math.sin(t * 0.4) * 0.04;
    return {
      tx:    x,
      ty:    y,
      tscl:  POSE_BASE_SCALE[3] * (1.0 + f.pulse * 0.22 + f.beat * 0.18),
      // Spin direction follows tangent of path
      trot:  phase.up * 0.25 + Math.sin(t * 0.8) * 0.4 * f.impact,
      tshx:  Math.sin(t * 0.7) * 0.18 * f.beat,
      tshy:  Math.cos(t * 0.5) * 0.10 * f.swell,
    };
  }

  function motionDance(t, f, dt) {
    phase.dance += dt * (1.6 + f.energy * 2.4 + f.pulse * 0.9);
    // Rose curve (k=3) → 3-petal flower path; chaotic on high energy
    const k     = 3;
    const r     = (0.32 + f.swell * 0.18) * Math.cos(k * phase.dance * 0.5);
    const ang   = phase.dance * 0.5 + t * 0.2;
    const x     = r * Math.cos(ang) + Math.sin(t * 1.6) * 0.08 * f.high;
    const y     = r * Math.sin(ang) + Math.cos(t * 1.3) * 0.06 * f.mid;
    // Spin freely; explode scale on each beat
    return {
      tx:    x,
      ty:    y,
      tscl:  POSE_BASE_SCALE[4] * (1.0 + f.beat * 0.30 + f.pulse * 0.20),
      trot:  phase.dance * 0.6 + Math.sin(t * 2.0) * 0.5 * f.impact,
      tshx:  Math.sin(t * 1.8 + phase.dance) * 0.22 * (0.4 + f.beat),
      tshy:  Math.cos(t * 2.2 + phase.dance) * 0.18 * (0.3 + f.swell),
    };
  }

  function targetForPose(idx, t, f, dt) {
    if (idx === 0) return motionNap(t, f, dt);
    if (idx === 1) return motionWalk(t, f, dt);
    if (idx === 2) return motionStand(t, f, dt);
    if (idx === 3) return motionUp(t, f, dt);
    return                 motionDance(t, f, dt);
  }

  // Different lerp speeds per pose so chill poses feel sluggish, dance poses snap.
  const POSE_LERP = [3.0, 6.0, 5.0, 9.0, 12.0];

  function tick(dt, t, features) {
    const f = features || {};
    f.energy = clamp01(f.energy);
    f.swell  = clamp01(f.swell);
    f.pulse  = clamp01(f.pulse);
    f.beat   = clamp01(f.beat);
    f.impact = clamp01(f.impact);
    f.low    = clamp01(f.low);
    f.mid    = clamp01(f.mid);
    f.high   = clamp01(f.high);
    f.hihat  = clamp01(f.hihat);

    // Crossfade
    if (blend < 1) blend = Math.min(1, blend + dt * blendSpeed);

    applyTransientReactions(f, dt);

    const tgt = targetForPose(activePose, t, f, dt);
    const k   = Math.min(1, dt * POSE_LERP[activePose]);

    const tx   = tgt.tx + beatRecoilP[0];
    const ty   = tgt.ty + beatRecoilP[1];
    const trot = tgt.trot + beatRecoilA;

    pos[0]  = lerp(pos[0],  tx,        k);
    pos[1]  = lerp(pos[1],  ty,        k);
    scl     = lerp(scl,     tgt.tscl,  k);
    rot     = lerp(rot,     trot,      k * 0.7);
    shear[0]= lerp(shear[0], tgt.tshx, Math.min(1, dt * 4.0));
    shear[1]= lerp(shear[1], tgt.tshy, Math.min(1, dt * 4.0));
    jitter  = impactJitter;

    // Trail integrates with delay — ghost copy that lags behind
    const trailLerp = Math.min(1, dt * 4.0);
    trail.x   = lerp(trail.x,   pos[0], trailLerp);
    trail.y   = lerp(trail.y,   pos[1], trailLerp);
    trail.scl = lerp(trail.scl, scl,    trailLerp);
    // Trail visibility scales with motion magnitude + energy
    const moveSq = (pos[0] - trail.x) ** 2 + (pos[1] - trail.y) ** 2;
    const motionMag = Math.sqrt(moveSq);
    const trailVisible = activePose === 3 || activePose === 4; // up/dance
    trail.alpha = trailVisible
      ? Math.min(0.7, motionMag * 12 + f.swell * 0.4)
      : Math.min(0.25, motionMag * 6);

    return {
      pose:     activePose,
      prevPose,
      blend,
      pos:      [pos[0], pos[1]],
      scl,
      rot,
      shear:    [shear[0], shear[1]],
      jitter,
      trail:    [trail.x, trail.y, trail.alpha, trail.scl],
      spinPhase,
    };
  }

  return { tick, setPose };
}
