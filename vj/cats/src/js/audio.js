// Audio Pipeline — Meyda (features) + aubio.js (beat tracking)
import Meyda from 'meyda';

export function createAudio() {
  let ctx, source, analyser, freqData, timeData;
  let meydaAnalyzer = null;
  let aubioTempo = null;

  const features = {
    bass: 0, mid: 0, high: 0, energy: 0,
    bassRaw: 0, midRaw: 0, highRaw: 0,
    bpm: 120,
    beat: 0,
    pulse: 0,
    impact: 0,
    swell: 0,
    kick: 0,
    snare: 0,
    hihat: 0,
    rms: 0,
    sub: 0,
    low: 0,
    spectralFlux: 0,
    brightness: 0,
    brightnessNorm: 0,
    hihatDensity: 0,
    hasAudio: false,
  };

  const hihatHistory = [];
  const fallbackIntervals = [];
  const kickHistory = [];
  const snareHistory = [];
  const hatHistory = [];
  let lastHihatTime = 0;
  let lastFallbackBeat = 0;
  let lastKickTime = 0;
  let lastSnareTime = 0;
  let lastHatTime = 0;
  let prevSub = 0;
  let prevBass = 0;
  let prevLowMid = 0;
  let prevMid = 0;
  let prevHighMid = 0;
  let prevHigh = 0;

  async function init(deviceId) {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    const constraints = {
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    };
    if (deviceId) constraints.deviceId = { exact: deviceId };
    const stream = await navigator.mediaDevices.getUserMedia({ audio: constraints });
    source = ctx.createMediaStreamSource(stream);
    setupAnalyser();
    await setupAubio();
    setupMeyda();
  }

  function setupAnalyser() {
    analyser = ctx.createAnalyser();
    analyser.fftSize = 4096;
    analyser.smoothingTimeConstant = 0.0;
    analyser.minDecibels = -90;
    analyser.maxDecibels = -10;

    const highpass = ctx.createBiquadFilter();
    highpass.type = 'highpass';
    highpass.frequency.value = 35;
    highpass.Q.value = 0.7;

    const compressor = ctx.createDynamicsCompressor();
    compressor.threshold.value = -24;
    compressor.knee.value = 24;
    compressor.ratio.value = 2.5;
    compressor.attack.value = 0.004;
    compressor.release.value = 0.18;

    source.connect(highpass);
    highpass.connect(compressor);
    compressor.connect(analyser);

    freqData = new Uint8Array(analyser.frequencyBinCount);
    timeData = new Uint8Array(analyser.fftSize);
  }

  async function setupAubio() {
    if (!window.aubio) return;
    try {
      const a = await window.aubio();
      aubioTempo = new a.Tempo(1024, 512, ctx.sampleRate);
    } catch (err) {
      aubioTempo = null;
    }
  }

  function setupMeyda() {
    meydaAnalyzer = Meyda.createMeydaAnalyzer({
      audioContext: ctx,
      source: analyser,
      bufferSize: 512,
      featureExtractors: ['spectralFlux', 'spectralCentroid', 'buffer'],
      callback: onMeydaFeatures,
    });
    meydaAnalyzer.start();
  }

  function onMeydaFeatures(f) {
    if (!f) return;
    features.spectralFlux = f.spectralFlux || 0;
    features.brightness = f.spectralCentroid || 0;
    features.brightnessNorm = clamp01((features.brightness - 400) / 2600);
    feedAubio(f.buffer);
    detectHihat();
  }

  function feedAubio(buffer) {
    if (!aubioTempo || !buffer) return;
    try {
      const buf = buffer instanceof Float32Array ? buffer : new Float32Array(buffer);
      if (aubioTempo.do(buf)) {
        features.beat = 1.0;
        const bpm = aubioTempo.getBpm();
        if (bpm > 60 && bpm < 200) features.bpm = Math.round(bpm);
      }
    } catch (_) {}
  }

  function detectHihat() {
    const now = performance.now();
    const isBright = features.brightnessNorm > 0.22;
    const isOnset = features.spectralFlux > 1.0;
    if (isBright && isOnset && (now - lastHihatTime) > 60) {
      lastHihatTime = now;
      hihatHistory.push(now);
    }
    while (hihatHistory.length && now - hihatHistory[0] > 1000) hihatHistory.shift();
    features.hihatDensity = Math.min(1, hihatHistory.length / 8);
  }

  function tick() {
    if (!analyser) return features;

    analyser.getByteFrequencyData(freqData);
    analyser.getByteTimeDomainData(timeData);

    const rawSub = bandAvg(30, 90);
    const rawBass = bandAvg(90, 220);
    const rawLowMid = bandAvg(220, 700);
    const rawMid = bandAvg(700, 2500);
    const rawHighMid = bandAvg(2500, 6000);
    const rawHigh = bandAvg(6000, 16000);
    const rawEnergy = rawSub * 0.20 + rawBass * 0.28 + rawLowMid * 0.18 + rawMid * 0.16 + rawHighMid * 0.11 + rawHigh * 0.07;
    const rms = computeRms();

    const kickDelta = Math.max(0, rawSub - prevSub) * 2.4 + Math.max(0, rawBass - prevBass) * 1.2;
    const snareDelta = Math.max(0, rawLowMid - prevLowMid) * 1.5 + Math.max(0, rawMid - prevMid) * 1.1;
    const hatDelta = Math.max(0, rawHighMid - prevHighMid) * 1.2 + Math.max(0, rawHigh - prevHigh) * 1.6 + features.spectralFlux * 0.08;

    prevSub = rawSub;
    prevBass = rawBass;
    prevLowMid = rawLowMid;
    prevMid = rawMid;
    prevHighMid = rawHighMid;
    prevHigh = rawHigh;

    const kickOn = detectAdaptiveOnset(kickHistory, kickDelta, 0.55, 140, 'kick');
    const snareOn = detectAdaptiveOnset(snareHistory, snareDelta, 0.40, 95, 'snare');
    const hatOn = detectAdaptiveOnset(hatHistory, hatDelta, 0.35, 55, 'hat');

    features.bassRaw = rawBass;
    features.midRaw = rawLowMid * 0.35 + rawMid * 0.65;
    features.highRaw = rawHighMid * 0.45 + rawHigh * 0.55;
    features.sub = smoothFeature(features.sub, rawSub, 0.35, 0.12);
    features.low = smoothFeature(features.low, (rawSub + rawBass) * 0.5, 0.35, 0.12);
    features.bass = smoothFeature(features.bass, rawBass, 0.38, 0.12);
    features.mid = smoothFeature(features.mid, rawLowMid * 0.30 + rawMid * 0.70, 0.28, 0.14);
    features.high = smoothFeature(features.high, rawHighMid * 0.35 + rawHigh * 0.65, 0.30, 0.16);
    features.rms = smoothFeature(features.rms, rms, 0.24, 0.09);
    features.energy = smoothFeature(features.energy, rawEnergy, 0.22, 0.08);
    features.kick = Math.max(kickOn, features.kick * 0.80);
    features.snare = Math.max(snareOn, features.snare * 0.84);
    features.hihat = Math.max(hatOn, features.hihat * 0.90);

    if (!aubioTempo) detectBeatFallback(rawBass);
    features.beat *= 0.82;
    features.pulse = Math.max(features.beat, features.pulse * 0.88, features.kick * 0.92);
    features.impact = Math.max(features.impact * 0.86, features.snare * 0.72 + features.hihat * 0.48);
    features.swell = lerp(features.swell, clamp01(features.energy * 0.72 + features.rms * 0.28), 0.08);
    features.hasAudio = (features.energy > 0.05) || (features.rms > 0.04);
    return features;
  }

  function detectBeatFallback(rawBass) {
    const now = performance.now();
    if (rawBass > features.bass * 1.6 && (now - lastFallbackBeat) > 260) {
      if (lastFallbackBeat > 0) {
        const interval = now - lastFallbackBeat;
        if (interval < 2000) {
          fallbackIntervals.push(interval);
          if (fallbackIntervals.length > 8) fallbackIntervals.shift();
          const avg = fallbackIntervals.reduce((a, b) => a + b, 0) / fallbackIntervals.length;
          features.bpm = Math.max(60, Math.min(200, Math.round(60000 / avg)));
        }
      }
      lastFallbackBeat = now;
      features.beat = 1.0;
    }
  }

  function bandAvg(loHz, hiHz) {
    const binHz = (ctx.sampleRate / 2) / analyser.frequencyBinCount;
    const lo = Math.max(0, Math.floor(loHz / binHz));
    const hi = Math.min(analyser.frequencyBinCount - 1, Math.ceil(hiHz / binHz));
    let sum = 0;
    for (let i = lo; i <= hi; i++) sum += freqData[i];
    return sum / (255 * (hi - lo + 1));
  }

  function computeRms() {
    if (!timeData) return 0;
    let sum = 0;
    for (let i = 0; i < timeData.length; i++) {
      const sample = (timeData[i] - 128) / 128;
      sum += sample * sample;
    }
    return Math.sqrt(sum / timeData.length);
  }

  function detectAdaptiveOnset(history, value, floor, cooldown, kind) {
    const now = performance.now();
    pushHist(history, value, 48);
    const threshold = adaptiveThreshold(history, floor);
    const lastTime = kind === 'kick'
      ? lastKickTime
      : kind === 'snare'
        ? lastSnareTime
        : lastHatTime;

    if (value > threshold && (now - lastTime) > cooldown) {
      if (kind === 'kick') lastKickTime = now;
      else if (kind === 'snare') lastSnareTime = now;
      else lastHatTime = now;
      return clamp01((value / Math.max(threshold, 1e-4) - 1.0) * 1.8);
    }
    return 0;
  }

  function adaptiveThreshold(history, floor) {
    if (!history.length) return floor;
    let mean = 0;
    for (const v of history) mean += v;
    mean /= history.length;

    let variance = 0;
    for (const v of history) variance += (v - mean) * (v - mean);
    variance /= history.length;
    return Math.max(floor, mean + Math.sqrt(variance) * 1.35);
  }

  function pushHist(arr, v, maxLen) {
    arr.push(v);
    if (arr.length > maxLen) arr.shift();
  }

  function smoothFeature(current, target, attack, release) {
    return target > current
      ? lerp(current, target, attack)
      : lerp(current, target, release);
  }

  function lerp(a, b, t) { return a + (b - a) * t; }
  function clamp01(v) { return Math.max(0, Math.min(1, v || 0)); }

  function resume() {
    if (ctx && ctx.state === 'suspended') ctx.resume();
  }

  return { init, tick, resume, features };
}
