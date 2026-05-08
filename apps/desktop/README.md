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
pnpm install

# Tauri CLI (one-time):
cargo install tauri-cli --version "^2.0"   # if not already installed

# Run dev:
pnpm tauri:dev
```

First launch will prompt for microphone access. System-audio capture (Zoom/Meet) lands in M4 and will require Screen Recording permission.

## Status

- M3 scaffold complete: bridge, mic capture, transcript view, references panel, doc upload.
- Not yet: system audio (M4), tray + hotkey + packaging (M5).
