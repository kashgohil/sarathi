# Desktop app

Tauri shell. Captures mic + system audio, renders the live transcript, references panel, and doc-upload UI. Talks to the Python sidecar over IPC.

- Frontend: TBD (React/Solid/Svelte — decide when scaffolding)
- Backend: Rust (Tauri)
- System audio on macOS: ScreenCaptureKit (requires Screen Recording permission)

Package manager: pnpm.
