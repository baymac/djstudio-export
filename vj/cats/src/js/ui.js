// UI — DOM-based overlays. Receives the audio module to handle device setup.
export function createUI(audio) {
  let pickerOpen   = false;
  let flashTimer   = null;
  let debugVisible = false;

  // ── Setup screen ──────────────────────────────────────────────────────────
  function setStatus(msg, isError) {
    const el = document.getElementById('setup-status');
    if (!el) return;
    el.textContent = msg;
    el.style.color = isError ? '#ff6655' : 'rgba(255,255,255,0.35)';
  }

  function showSetup() {
    const el = document.getElementById('setup');
    if (!el) return;
    el.style.display = 'flex';
    requestAnimationFrame(() => { el.style.opacity = '1'; });
  }

  function dismissSetup() {
    const el = document.getElementById('setup');
    if (!el) return;
    el.style.opacity = '0';
    el.style.pointerEvents = 'none';
    setTimeout(() => { el.style.display = 'none'; }, 600);
  }

  async function startDefault() {
    const setupEl = document.getElementById('setup');
    if (!setupEl || setupEl.style.display === 'none') return;
    setStatus('');
    const saved = localStorage.getItem('rbShowDevice') || null;
    try {
      await audio.init(saved);
      dismissSetup();
    } catch (err) {
      if (err.name === 'NotAllowedError') {
        setStatus('Microphone blocked — allow in System Settings → Privacy → Microphone', true);
      } else if (err.name === 'NotFoundError') {
        setStatus('Device not found — set BlackHole 2ch as Mac input or pick below', true);
      } else {
        setStatus(err.message, true);
      }
    }
  }

  async function togglePicker() {
    const list = document.getElementById('device-list');
    pickerOpen = !pickerOpen;
    list.style.display = pickerOpen ? 'flex' : 'none';
    if (!pickerOpen) return;
    setStatus('loading device list…');
    try {
      const tmp = await navigator.mediaDevices.getUserMedia({ audio: true });
      tmp.getTracks().forEach(t => t.stop());
      const devices = await navigator.mediaDevices.enumerateDevices();
      const inputs  = devices.filter(d => d.kind === 'audioinput');
      setStatus('');
      list.innerHTML = '';
      if (inputs.length === 0) {
        list.innerHTML = '<div style="color:rgba(255,255,255,0.3)">No audio inputs found</div>';
        return;
      }
      inputs.forEach(dev => {
        const btn = document.createElement('button');
        btn.className = 'device-btn';
        if (/blackhole|aggregate|controller/i.test(dev.label)) btn.classList.add('blackhole');
        btn.textContent = dev.label || ('Input ' + dev.deviceId.slice(0, 12));
        btn.onclick = async () => {
          setStatus('connecting to ' + btn.textContent + '…');
          btn.style.opacity = '0.5';
          try {
            await audio.init(dev.deviceId);
            localStorage.setItem('rbShowDevice', dev.deviceId);
            dismissSetup();
          } catch (err) {
            setStatus(err.name + ': ' + err.message, true);
            btn.style.opacity = '1';
          }
        };
        list.appendChild(btn);
      });
    } catch (err) {
      setStatus('Permission denied — ' + err.message, true);
    }
  }

  // Wire up setup screen clicks (replaces inline onclick in HTML)
  document.getElementById('setup')?.addEventListener('click', startDefault);
  document.getElementById('toggle-picker')?.addEventListener('click', e => {
    e.stopPropagation();
    togglePicker();
  });

  // ── Scene-name flash ──────────────────────────────────────────────────────
  function flashSceneName(name) {
    const el = document.getElementById('scene-name');
    if (!el) return;
    el.innerText = name;
    el.style.opacity = '1';
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => { el.style.opacity = '0'; }, 1800);
  }

  // ── Duet pose labels (Mewtwo & Chewtwo) ───────────────────────────────────
  // Stay visible the entire time the duet pose is showing.
  function showDuetLabels() {
    document.getElementById('duet-labels')?.classList.add('show');
  }
  function hideDuetLabels() {
    document.getElementById('duet-labels')?.classList.remove('show');
  }

  // ── Resting state — DJ branding poster shown when no music is playing ────
  function showRestScreen() {
    document.getElementById('rest-screen')?.classList.add('show');
  }
  function hideRestScreen() {
    document.getElementById('rest-screen')?.classList.remove('show');
  }

  // ── Debug bar ─────────────────────────────────────────────────────────────
  function updateDebug(features, stateLabel, countdown, sectionName, sectionCountdown) {
    if (!debugVisible) return;
    setBar('bar-bass', features.bass);
    setBar('bar-mid',  features.mid);
    setBar('bar-high', features.high);
    setText('val-state',     stateLabel);
    setText('val-energy',    features.energy.toFixed(2));
    setText('val-anim-left', countdown == null ? '—' : countdown.toFixed(1) + 's');
    setText('val-section',   sectionName || '--');
    setText('val-sec-left',  sectionCountdown == null ? '—' : sectionCountdown.toFixed(1) + 's');
  }

  function toggleDebug() {
    debugVisible = !debugVisible;
    document.getElementById('debug')?.classList.toggle('visible', debugVisible);
  }

  function setBar(id, v) {
    const el = document.getElementById(id);
    if (el) el.style.width = (Math.max(0, Math.min(1, v)) * 100).toFixed(0) + '%';
  }
  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) document.documentElement.requestFullscreen();
    else document.exitFullscreen();
  }

  return {
    showSetup, dismissSetup,
    flashSceneName, showDuetLabels, hideDuetLabels,
    showRestScreen, hideRestScreen,
    updateDebug, toggleDebug, toggleFullscreen,
  };
}
