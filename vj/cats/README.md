# cats — VJ visualizer

An audio-reactive VJ visualizer built around a DJ's cats — procedural cat poses in WebGL, real cat photos that dance to the music, and cinematic AI videos that ping-pong loop. Built with p5.js, Meyda, and aubio.js. No backend, runs entirely in the browser.

Tap, allow mic, play music. The show cycles through four sections forever.

Ships as a sub-project of the [`dj`](../../README.md) repo at `vj/cats/`. Runs locally only — there's no hosted deploy.

---

## Quick start

> First time? Run the [setup steps](../../README.md#setup) from the repo root to install dependencies and put `dj` on your PATH.

```bash
dj vj cats start         # from anywhere — npm install runs on first launch
                         # opens https://cats.localhost in the default browser
dj vj cats stop          # kills the background process group
```

The `dj vj <name> start/stop` command auto-discovers any `vj/<name>/` directory
that has a `package.json` with a `dev` script, so the same flow works for any
future VJ app you drop in next to `cats/`.

1. Open the URL the command printed (`https://cats.localhost` or `…localhost:1355`) in Chrome or Edge on a laptop with a working microphone.
2. Tap **"TAP TO START"** and grant microphone permission.
3. Play music nearby — either from speakers (laptop mic picks it up) or by routing system audio (see [Connecting audio](#connecting-audio) below).
4. Watch the show cycle: **intro video → procedural cat dot poses → real cat photos → cinematic catwoman videos → repeat.**

**Keyboard shortcuts:**

| Key | Action |
| --- | --- |
| `F` | Toggle fullscreen |
| `D` | Toggle debug HUD (bass/mid/high bars + state + timers) |
| `N` | Skip to next section (6-second manual preview) |
| `M` | Skip to next scene within current section (6-second preview) |
| `R` | Rotate canvas 90° / -90° / 180° (for sideways-mounted projectors) |

**URL params:**

- `?rot=90`, `?rot=-90`, `?rot=180` — start rotated (same as pressing R)

---

## How visuals react to music

The mic input goes through a 35 Hz highpass and a dynamics compressor, then into **Meyda** for FFT analysis and **aubio.js** for BPM and onset detection. The result is five audio dimensions that drive every visual element in real time.

### The five audio dimensions

| Dimension | Frequency band | Drives |
| --- | --- | --- |
| **Low** | 30–220 Hz (bass + sub) | Scale pumps, gait speed, orbital radii, camera pitch |
| **Mid** | 700–2500 Hz | Head tilt, midrange pattern frequencies, EQ bar heights |
| **High** | 6–16 kHz (treble) | Yaw spin, jitter, sparkle, rim halos |
| **Beat/Pulse** | Kick + snare + hi-hat onsets | Jumps, recoils, particle flashes, scale snaps |
| **Swell** | Smooth energy blend (72% RMS + 28% amplitude) | Breathing, glow intensity, background haze |

Details in `src/js/audio.js:47-194` (feature extraction) and `src/js/state.js:80-127` (audio → uniforms math).

### Pose-specific reactions

Every pose has its own audio-reactive personality:

**Cat dot section (procedural shader):**

- **Sleep** — slow breathing, low-energy ambient drift
- **Sit** — orbital particle background, bass pumps the radii
- **Yoga** — 12-fold mandala particle formation
- **Cobra** — zigzag, beat triggers radial push
- **Run** — gait frequency tracks bass + swell, tail amplitude jumps on impact
- **Spin** — Archimedean spiral, high frequencies add jitter
- **Duet** — Mewtwo (orange, left) + Chewtwo (grey, right), twin clusters

**Meow photo section:**

- **Nap** — dreamy zoom/bob/drift; paw twitches on impact, breathing follows swell
- **Walk** — gait tracks bass; beats trigger jumps; alternates between horizontal, vertical, diagonal, lissajous paths
- **Stand** — OIIA-meme spin: alternates still ↔ blurry spin; beats can trigger early spin bursts
- **Up** — figure-8 lissajous; orbital radius scales with energy
- **Dance** — rose-curve 3-petal path; scale explodes on beats

### Silence behavior

After 1.5 seconds of silence, the visualizer switches to a **static rest screen** (DJ logo + cat photo). When music returns, the deck resets to the intro and the show starts cleanly from the top.

### Test it yourself

Press **D** to enable the debug HUD. You'll see live bars for bass/mid/high, the current pose/section/countdown, and the energy value. Play sparse music (acoustic) vs. dense music (techno) and watch the bars and visuals react differently.

---

## The four scenes — what they are and how to remix them

Every visual element in this app is meant to be replaced with your own content. These are starting points — use your creativity.

### 1. Intro (6 seconds, plays at show start + after every full cycle)

What it is: a single short video used as the DJ's signature moment. Plays once each cycle, then the show moves on.

**How to swap with your branding:**

1. Make a logo + a still image of your DJ persona using Gemini, ChatGPT image gen, Midjourney, or your own art.
2. Animate it into a 4–6 second motion clip with **Kling** (available inside ElevenLabs Video Generation). Give Kling the still as the starting frame and prompt for the vibe you want — smoke, neon, beat drop, etc.
3. Save the result as `public/intro.mp4`.
4. Adjust the `duration` field in `src/js/deck.js:13` to match your clip length (currently 6000 ms).

---

### 2. Cat — abstract dot-grid poses (120 s)

What it is: a procedural cat drawn as glowing dots in WebGL. **Seven poses** (sleep, sit, yoga, cobra, run, spin, duet), each with its own audio-reactive particle background. Two named cats: **Mewtwo** (orange, active poses) and **Chewtwo** (grey, calm poses).

**Files:**

- `src/shaders/cat.js` — pose dispatch + duet renderer
- `src/shaders/poses/cat_pose_*.js` — one file per pose (SDF/distance-field shaders)
- `src/js/state.js` — audio → pose blending and uniforms

**How to remix** (light to heavy):

- **Change cat colors:** edit `MEWTWO` and `CHEWTWO` constants in `src/js/state.js:12-13`.
- **Tune audio reactivity:** tweak the formulas at `src/js/state.js:98-127` (e.g., `uSpeed = 0.8 + swell * 6.8 + low * 2.2`).
- **Add a new pose:** drop a new `cat_pose_xxx.js` in `src/shaders/poses/`, register it in `cat.js` dispatch, add it to `POSE_PRESETS` in `state.js`, list it in the `cat` section of `deck.js`. The existing pose files are good templates.

This is the most code-heavy section. If you're not into GLSL, skip it and remix the meow and catwoman sections first.

---

### 3. Meow — real cat photos with audio-reactive motion (120 s)

What it is: **five photos** of a real cat, each in a different pose (nap, walk, stand, up, dance), moved + spun + jittered by music. The stand pose has a special OIIA-meme-style still-then-spin-blob behavior.

**The asset recipe** (the magic for non-coders):

1. Take 5 photos of your cat in different poses. (Or use existing photos — Google your own cam roll.)
2. Run each through **[remove.bg](https://remove.bg)** to get clean transparent PNG cutouts.
3. **Optional but powerful:** feed each cutout to Gemini or ChatGPT and prompt something like:
   - *"Create a 3D-style render of this cat, extrapolating any missing limbs, posed in a standing position on its hind legs."*
   - *"Take this cat's face and fit it onto a dynamic cat body that's mid-dance, with motion blur."*
   - *"Render this cat as if it's pouncing upward, full body visible."*
   This is how the demo gets stylized poses from a single cat photo.
4. Save the final PNGs as `src/assets/meow/{nap,walk,stand,up,dance}.png`.

**Tips:**

- Keep the cat roughly centered with a transparent background. The shader uses the PNG's alpha channel as the mask.
- The stronger the pose photo, the better the visual punch. The OIIA spin (stand pose) is the punchline of this section — give it the most "standing upright" energy.

**What each photo should look like to match the motion:**

| File | Motion | Best photo type |
| --- | --- | --- |
| `nap.png` | Gentle zoom / bob / drift | Sleepy, curled |
| `walk.png` | Horizontal / vertical / diagonal / lissajous + jumps | Walking, alert |
| `stand.png` | Still → spin blur (OIIA cat meme) | Standing upright on hind legs |
| `up.png` | Figure-8 lissajous orbit | Pouncing, upright |
| `dance.png` | Rose-curve 3-petal path, explodes on beat | Most dramatic, mid-action |

---

### 4. Catwoman — cinematic AI videos with ping-pong looping (120 s)

What it is: **two short AI-generated videos** that play forward, then in reverse, then forward again — creating a hypnotic loop without any visible cut. The demo themes are CYBERPUNK and CYBORG.

**The recipe:**

1. Take a photo of yourself (or anyone) with a cat — real cat in your arms, or a printed cat picture you're holding.
2. Use Gemini, ChatGPT, or Midjourney to generate a **starting image** with a theme. Some prompts to try:
   - *"This person as a cyberpunk catwoman with neon Tokyo skyline behind her, rain, holographic ads, anime cinematic style."*
   - *"This person fused with a cybernetic feline in a chrome laboratory, sci-fi, dramatic lighting."*
   - *"This person as a vintage cat goddess in a desert temple, golden hour, Wes Anderson palette."*
3. Generate a complementary **ending image** with the same character but a different pose or background detail.
4. Feed both images to **Kling** (inside ElevenLabs Video Generation). Set the start frame and the end frame, prompt the morph (camera move, weather change, lighting shift). Generate a 4–6 second clip.
5. Save as `public/your_scene.mp4`.
6. **Pre-encode the reverse** for ping-pong playback:
   ```bash
   ffmpeg -y -i public/your_scene.mp4 -vf reverse -an \
     -c:v libx264 -preset slow -crf 20 \
     -movflags +faststart public/your_scene_rev.mp4
   ```
   Why each flag matters:
   - `-vf reverse` — the actual frame reversal
   - `-an` — strip audio (the player keeps videos muted anyway, smaller file)
   - `-c:v libx264 -preset slow -crf 20` — re-encode to a clean keyframe structure; the original's sparse keyframes are what made rAF-driven reverse seeking drop frames
   - `-movflags +faststart` — moves the `moov` atom to the front of the file so the reverse video can start playing instantly at the swap point. Without this you get a freeze frame at the forward→reverse transition while the browser fetches the moov atom from the end of the file.
7. Register it in `src/js/deck.js:43-47`:
   ```js
   { type: 'video', src: '/your_scene.mp4', label: 'YOUR_LABEL' },
   ```

The video player will auto-load `your_scene_rev.mp4` based on the filename (`src.replace(/\.mp4$/i, '_rev.mp4')` in `video_player.js:40`). Both videos play forward natively, swapping on `ended` events.

### Anti-stutter measures in `video_player.js`

If you're porting the player to another project, these two details matter:

- **Pre-buffer both legs at construction** — both `<video>` elements are created and `preload='auto'` + `load()`'d up front (`video_player.js:18-35`), not on-demand. The reverse clip is already in the browser's buffer before the forward leg finishes.
- **`timeupdate` safety net** — the leg swap fires on `ended`, but also as a fallback when `currentTime >= duration - 0.05` (`video_player.js:87-100`). Some codecs / browsers don't reliably emit `ended`, and without this fallback you get a stuck frame for several hundred ms at the swap.

---

## Adding your own scenes

The deck is data-driven. Add a section to the `SECTIONS` array in `src/js/deck.js:11`:

```js
{
  name: 'your_section',
  duration: 60000,  // ms; defaults to 2 minutes if omitted
  anims: [
    { type: 'video', src: '/your_video.mp4', label: 'NAME' },
    // or
    { type: 'cat', pose: 'sleep' },   // reuse an existing procedural pose
    { type: 'meow', pose: 'dance' },  // reuse an existing photo pose
  ],
},
```

Currently supported animation types:

- `cat` — procedural dot shader, references a pose name
- `meow` — photo + audio-reactive transforms, references a pose name
- `video` — mp4 with optional ping-pong (default on; set `pingPong: false` for single-shot like the intro)

### Ideas for new scenes

- **Audio-reactive text** — DJ name or current track title slamming in on beats. New scene type, drop in `src/shaders/`.
- **Photo wall** — fan submissions or tour photos, cycling on beat.
- **3D model** — load a GLB of a cat through p5.js / three.js, spin it with audio.
- **Live camera** — webcam feed with kaleidoscope effect.
- **Lyric sync** — hand-typed lyrics synced to the set list, advancing on bar count.
- **GIF wall** — `public/gifs/` folder, random pick on every beat drop.

These are creative prompts. The deck happily accepts any new `type` as long as you handle it in `src/js/main.js`'s `handleAnimChange` function (around line 124).

---

## How the background visuals work

**Cat section backgrounds** — `src/shaders/cat.js`. 48 weight-blended flying particles per pose. Each pose has its own formation:

- Sleep → ambient drift
- Sit → concentric orbits
- Yoga → 12-fold mandala
- Cobra → zigzag lanes
- Run → horizontal speed lanes
- Spin → Archimedean spiral
- Duet → twin clusters

Particles react to audio in real time: bass pumps the orbital radii, beats push particles outward, treble adds micro-jitter, impact (snare hits) flashes size and brightness.

**Meow section backgrounds** — `src/shaders/meow.js`. Each photo pose gets its own kaleidoscopic accent layer:

- Nap → dreamy nebula + stars + aurora
- Walk → Tron grid + parallax skyline + diamonds
- Stand → solar mandala + beat-pulsed rings
- Up → synthwave 24-bar EQ + shockwaves + neon pillars
- Dance → 6-fold kaleidoscope + lattice + plasma

All accent layers are modulated by `uPulse`, `uBeat`, `uSwell`, `uLow`, `uMid`, `uHigh` in real time.

**Catwoman section** — the video is the visual; no overlay.

**Rest screen** — static logo and cat photo, shown when silence persists past 1.5 seconds.

---

## Connecting audio

The visualizer reacts to whatever the browser hears through `getUserMedia`. Four ways to feed it audio:

### Quickest test (works on any OS, no install)

Use your laptop's built-in mic. Play music from speakers (your laptop, your phone, anything nearby). The mic picks it up — works fine for testing, picks up room noise and your voice.

### Best for live use (macOS)

Install **[BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole)** (free, open source).

1. Open **Audio MIDI Setup** → create a **Multi-Output Device** that routes audio to both BlackHole and your real speakers / headphones. (So you can hear it AND the browser can see it.)
2. Set your DJ software's output (or the system output) to the multi-output device.
3. In the visualizer's setup screen, click **"pick audio device"** and select **BlackHole 2ch**. (It's highlighted in the device list.)
4. The visualizer now sees the DJ software's output directly — zero room noise, perfect bass response.

### Best for live use (Windows)

Install **[VB-Audio Cable](https://vb-audio.com/Cable/)** (free). Same idea as BlackHole — route your DJ software's output through the virtual cable, pick it as the input device in the visualizer.

### Pro setup (physical hardware)

Plug your DJ mixer's output into an audio interface with a loopback channel (Focusrite Scarlett, RME, etc.). Route the loopback channel as the browser's input device.

### Browser permissions

- Microphone permission required (`getUserMedia`). Chrome remembers it after the first grant.
- **HTTPS is required** for `getUserMedia` to work. `localhost` is exempt, so `npm run dev` works fine without any cert setup.

### Troubleshooting

- **No bars moving in the debug HUD (D key)?** Wrong device selected. Click "pick audio device" on the setup screen, choose the right input.
- **Audio is glitching?** Browser is throttling background tabs — keep the visualizer tab visible / foreground.
- **Videos don't autoplay?** They will after the first user interaction. Tap the screen once and they'll unlock.
- **Bass not registering?** The 35 Hz highpass kills sub-rumble. If your music is very bass-heavy, the energy is still captured via the `low` band (30–220 Hz).

---

## Local development

`dj vj cats start/stop` is the canonical way to run the app — it wraps vite in
portless so you get an HTTPS URL (`https://cats.localhost`), which `getUserMedia`
requires for the microphone permission to stick.

If you want to run vite directly (no portless, no HTTPS, just `localhost:5173`):

```bash
cd vj/cats
npm install
npm run dev          # http://localhost:5173
npm run build        # builds to dist/
npm run preview      # serves dist/ locally
```

Requirements: **Node 18+**.

Stack: Vite + p5.js + Meyda + aubio.js. All audio analysis is client-side; there is no backend, no deploy pipeline.

---

## File map

```
src/
  js/
    main.js          # entry point, rotation, rest screen, keys
    audio.js         # mic input + meyda + aubio.js features
    state.js         # audio → cat pose uniforms + blending
    deck.js          # section + animation cycling
    scene.js         # shader compile + uniform dispatch
    meow_anim.js     # per-pose motion logic for photo cats
    video_player.js  # ping-pong video playback
    ui.js            # setup screen, debug HUD, overlays
  shaders/
    cat.js           # cat dot shader dispatch + duet
    meow.js          # photo cat shader + kaleidoscope accents
    poses/           # one file per cat pose (SDF)
    vertex.js        # shared vertex shader
  assets/meow/       # 5 cat photos — swap these for your cat
public/              # videos + branding — swap these for your DJ
```

---

Credits, social links, and the MIT license live at the [repo root](../../README.md#credits) — featured cats **Mewtwo** (orange) and **Chewtwo** (grey).
