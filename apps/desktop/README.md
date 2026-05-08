# Desktop app

Tauri 2.x shell. Captures mic audio, renders the live transcript and references panel, and forwards doc-upload requests to the Python sidecar over NDJSON.

## Layout

```
apps/desktop/
  package.json              React + Vite + Tailwind
  vite.config.ts
  tsconfig.json
  index.html
  tailwind.config.js
  postcss.config.js
  src/
    main.tsx                React entry
    App.tsx                 Top-level layout
    index.css               Tailwind base
    components/
      TranscriptView.tsx
      ReferencesPanel.tsx
      DocUpload.tsx
    lib/
      sidecar.ts            invoke + event wrappers (sidecar://event)
      audio.ts              getUserMedia → 16kHz int16 PCM → base64
  src-tauri/
    Cargo.toml
    tauri.conf.json
    capabilities/default.json
    src/
      main.rs
      lib.rs                command registry
      sidecar.rs            child-process bridge (NDJSON in/out)
```

## How the bridge works

1. Frontend calls `sidecar_start` (Tauri command) → Rust spawns `sarathi serve` and starts pump tasks on its stdout/stderr.
2. Each NDJSON line on the sidecar's stdout is emitted as a Tauri event `sidecar://event`. The frontend subscribes via `onSidecarEvent`.
3. Frontend calls `sidecar_send({ type, ... })` → Rust serializes JSON to one line and writes it to the sidecar's stdin.
4. `sidecar_stop` sends a cooperative `{type:"shutdown"}`, then waits for the child to exit.

In dev, the Rust shell finds the sidecar by walking up from `CARGO_MANIFEST_DIR` until it sees `apps/sidecar`, then runs `uv run sarathi serve` from there. Override with `SARATHI_SIDECAR_BIN` (path to a built sidecar binary) or `SARATHI_SIDECAR_CWD` (path to the sidecar package).

## Setup

```bash
cd apps/desktop
bun install

# Tauri CLI (one-time):
cargo install tauri-cli --version "^2.0"   # if not already installed

# Build the Swift system-audio helper (one-time / when changed):
bash src-tauri/macos/build.sh             # produces .build/release/audio-tap

# Run dev:
bun tauri:dev
```

First launch will prompt for microphone access. The first time you select "System audio" or "Mic + system" in the source dropdown, macOS prompts for Screen Recording permission; if denied, the app shows a banner with a button that deep-links to System Settings.

## Audio sources

Selectable from the top-bar dropdown:

- **Microphone** — `getUserMedia` in the webview, downsampled to 16 kHz mono int16 in an AudioWorklet, sent via `mic_pcm` command.
- **System audio** — Swift helper (`audio-tap`) using ScreenCaptureKit, captures everything the system plays (Zoom/Meet/Teams). Raw int16 LE PCM on stdout, JSON status on stderr.
- **Mic + system** — both streams feed a Rust mixer (`mixer.rs`) which sample-aligns them on a 250 ms tick, sums with int16 clipping, and forwards a single combined stream. Includes drift correction (max 1.5 s) and single-source fallback if one channel goes silent.

## Permissions, packaging, backpressure

- `Info.plist` declares `NSMicrophoneUsageDescription` and `NSScreenCaptureUsageDescription`. macOS shows these strings in its permission prompt.
- `macos.entitlements` grants the audio-input entitlement and library validation flags needed for the bundled helper.
- The Swift helper proactively calls `CGPreflightScreenCaptureAccess()` and `CGRequestScreenCaptureAccess()` for deterministic permission UX, plus a multi-signal `classifyError()` for the catch-all path.
- Audio frames go through `try_send` on a bounded mpsc channel, so a slow sidecar drops frames instead of stalling the audio thread; the mixer additionally caps each per-source ring at 5 s.
- `tauri.conf.json` declares the helper as `bundle.externalBin`; `macos/stage-binaries.sh` (run from `beforeBundleCommand`) places the built Swift binary at `binaries/audio-tap-<triple>` so Tauri picks it up. `system_audio::resolve_bin` checks the bundled location first, dev paths next.

## Tray + global hotkey

- Menu-bar tray icon with **Toggle Recording**, **Show Sarathi**, **Quit**.
- Global hotkey: `Cmd+Shift+R` toggles recording from anywhere on the system. Uses `tauri-plugin-global-shortcut`.
- Both fire a `tray://toggle-record` event; `App.tsx` reads the latest status via a ref and flips between `start/stopRecording`.

## Status

- M3 ✅ — bridge, mic capture, transcript view, references panel, doc upload.
- M4 ✅ — Swift `audio-tap`, system-audio bridge, source selector, permission banner, sample-aligned mixer, bundled-binary resolution, Info.plist, entitlements, backpressure.
- M5 ✅ — diarization, retention vacuum, tray + hotkey, packaging recipe (`docs/packaging.md`). PyInstaller spec + bundled-sidecar resolver. First-run model download UI is the only remaining polish.
