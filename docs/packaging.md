# Packaging the Sarathi macOS app

End-to-end recipe for producing a signed, notarized `.dmg` from a clean checkout. Targets M-series Macs running macOS 13+.

## Components

| Component | Source | Build output |
|---|---|---|
| Tauri shell | `apps/desktop/src-tauri` | Rust binary (the .app's main executable) |
| `audio-tap` | `apps/desktop/src-tauri/macos` | Swift binary, system-audio helper |
| Sidecar | `apps/sidecar/` | PyInstaller `onedir` bundle (`sarathi-sidecar` + libs) |

All three live inside the `.app`'s `Contents/MacOS/` (Tauri places `externalBin` siblings of the main binary). Models are NOT bundled — they download to `~/Library/Application Support/sarathi/models/` on first use.

## One-shot build

```bash
# 0. Toolchains (one-time)
cargo install tauri-cli --version "^2.0"
xcode-select --install     # for swift
brew install python@3.11
curl -LsSf https://astral.sh/uv/install.sh | sh

# 1. Sidecar (PyInstaller onedir, ~3 GB with [ml])
cd apps/sidecar
uv sync --extra ml --extra dev
uv run pyinstaller sarathi.spec   # writes apps/sidecar/dist/sarathi-sidecar/

# 2. Desktop frontend
cd ../desktop
pnpm install
pnpm build                         # writes apps/desktop/dist/

# 3. Swift helper
bash src-tauri/macos/build.sh release

# 4. Stage binaries (audio-tap + sarathi-sidecar) into src-tauri/binaries/
bash src-tauri/macos/stage-binaries.sh release

# 5. Tauri build (assembles .app, .dmg)
pnpm tauri:build
```

The `beforeBundleCommand` in `tauri.conf.json` runs steps 3–4 automatically — but step 1 (PyInstaller) is intentionally NOT in the bundle hook because it's slow and you don't want it firing on every dev rebuild.

If you skip step 1, the staging script writes a shim that defers to `uv run sarathi serve`, so the resulting `.app` will only work on machines that have `uv` and the sidecar source tree available. Useful for internal preview builds, not for distribution.

## Code-signing & notarization

Tauri 2 reads signing config from environment variables. Set these before `pnpm tauri:build`:

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export APPLE_CERTIFICATE="$(base64 -i path/to/cert.p12)"
export APPLE_CERTIFICATE_PASSWORD="..."
export APPLE_ID="you@example.com"
export APPLE_PASSWORD="app-specific-password"
export APPLE_TEAM_ID="TEAMID"
```

`tauri.conf.json` already references `macos.entitlements` which grants the audio-input entitlement plus the library-validation flags needed for the embedded helpers. If you add new entitlements, edit that file.

After `pnpm tauri:build`, notarize:

```bash
xcrun notarytool submit \
  apps/desktop/src-tauri/target/release/bundle/dmg/Sarathi_0.0.1_aarch64.dmg \
  --apple-id "$APPLE_ID" --password "$APPLE_PASSWORD" --team-id "$APPLE_TEAM_ID" \
  --wait

xcrun stapler staple \
  apps/desktop/src-tauri/target/release/bundle/dmg/Sarathi_0.0.1_aarch64.dmg
```

## Bundle inspection

After build, sanity check that the `.app` carries everything:

```bash
APP="apps/desktop/src-tauri/target/release/bundle/macos/Sarathi.app"
ls -la "$APP/Contents/MacOS/"
# expected: Sarathi, audio-tap-aarch64-apple-darwin, sarathi-sidecar-aarch64-apple-darwin

# Check signatures
codesign -dvv "$APP"
codesign -dvv "$APP/Contents/MacOS/audio-tap-aarch64-apple-darwin"
codesign -dvv "$APP/Contents/MacOS/sarathi-sidecar-aarch64-apple-darwin"

# Check entitlements
codesign -d --entitlements - "$APP"
# should list NSScreenCaptureUsageDescription via Info.plist + audio-input entitlement
```

## First-run model download

On first launch, the sidecar lazy-loads each model as it's first used. Default config (`config/defaults.toml`) is tuned for ~7.5 GB total — sizes below.

### Default preset (~7.5 GB)

| Model | Size | When it loads |
|---|---|---|
| whisper-large-v3-turbo (int8) | ~1.0 GB | first audio frame |
| BGE-M3 | ~2.3 GB | first chunk embed / first query |
| Qwen2.5-7B-4bit (MLX) | ~4.0 GB | first answer generation |
| silero-vad | ~2 MB | bundled with the `silero-vad` pip package |
| **Total** | **~7.3 GB** | |

### Optional add-ons (off by default)

| Model | Size | Enable via |
|---|---|---|
| bge-reranker-v2-m3 | ~1.1 GB | `[rerank].enabled = true` |
| Qwen2.5-14B-4bit (MLX) | ~8.0 GB | `[llm].model = "mlx-community/Qwen2.5-14B-Instruct-4bit"` |
| pyannote diarization | ~30 MB | `[diarize].enabled = true` (needs `HF_TOKEN`) |
| PaddleOCR (devanagari) | ~500 MB | downloaded only when an image-only PDF is ingested |

### Quality presets

- **Lighter (~4 GB):** `[asr].model = "large-v3-turbo"` + `[asr].compute_type = "int8"` + `[llm].model = "mlx-community/Qwen2.5-3B-Instruct-4bit"`. Quality drop is real on Gujarati but the app is usable.
- **Default (~7.5 GB):** as shipped.
- **Heavier (~11.5 GB):** flip the reranker on and switch the LLM to 14B-4bit. Best end-to-end quality but slower first answer (8 GB model load is ~30s on M4 the first time).

The sidecar emits `info` events on stderr while models download. Forwarding these to a first-run progress UI is the only major M5+ polish item still pending.

## Troubleshooting

- **"audio-tap not built; run macos/build.sh first"** — the staging script ran before the Swift build. Run `bash src-tauri/macos/build.sh release` first.
- **Sidecar exits immediately with `permission_denied`** — that's the screen-recording prompt. Click "Open System Settings" in the in-app banner; toggle Sarathi on under Privacy & Security → Screen Recording.
- **MLX model loads slowly on first run** — expected. ~8 GB of weights map into unified memory; subsequent loads are fast (already memory-mapped).
- **`pyannote` errors with HTTP 401** — accept the model license at https://huggingface.co/pyannote/speaker-diarization-3.1, generate a read token, set `HF_TOKEN`, restart.
- **Bundle is huge (~15 GB)** — that's torch + mlx + whisper + BGE + reranker. To ship a lighter build, omit the `[ml]` extra at PyInstaller time; the sidecar still produces stub answers and the eval harness still runs.
