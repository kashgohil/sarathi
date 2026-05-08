//! System-audio capture bridge.
//!
//! Spawns the Swift `audio-tap` helper, reads its raw int16 PCM stdout in
//! ~250ms batches, base64-encodes them, and sends them to the sidecar as
//! `audio` commands. Reads JSON status lines from the helper's stderr and
//! forwards them to the frontend so it can react to permission denials.
//!
//! Resolution:
//!   1. `SARATHI_AUDIO_TAP_BIN` env var (path to a built audio-tap binary).
//!   2. Walk up from CARGO_MANIFEST_DIR to find
//!      `src-tauri/macos/.build/release/audio-tap`.

use crate::mixer;
use anyhow::{anyhow, Context, Result};
use serde_json::Value;
use std::path::PathBuf;
use std::process::Stdio;
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::{mpsc, oneshot};

const EVENT_NAME: &str = "system-audio://event";

/// PCM at 16 kHz mono int16 = 32 KB/sec. Send at most ~250 ms at a time
/// to match the mic capture cadence; the sidecar VAD doesn't care about
/// finer granularity.
const FRAME_BYTES: usize = 16_000 * 2 * 250 / 1000; // 8000 bytes

pub struct SystemAudioHandle {
    tx: mpsc::Sender<Cmd>,
}

enum Cmd {
    Stop(oneshot::Sender<()>),
}

impl SystemAudioHandle {
    pub fn spawn(
        app: AppHandle,
        on_pcm: impl Fn(Vec<i16>) + Send + Sync + 'static,
    ) -> Result<Self> {
        let bin = resolve_bin(&app)?;
        let mut cmd = Command::new(&bin);
        cmd.stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);

        let mut child: Child = cmd
            .spawn()
            .with_context(|| format!("spawning audio-tap: {}", bin.display()))?;

        let stdout = child.stdout.take().ok_or_else(|| anyhow!("no stdout"))?;
        let stderr = child.stderr.take().ok_or_else(|| anyhow!("no stderr"))?;
        let stdin = child.stdin.take().ok_or_else(|| anyhow!("no stdin"))?;

        // Pump stderr → frontend (status JSON) and into our own logging.
        {
            let app = app.clone();
            tokio::spawn(async move {
                let mut lines = BufReader::new(stderr).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    if let Ok(v) = serde_json::from_str::<Value>(&line) {
                        let _ = app.emit(EVENT_NAME, v);
                    } else {
                        let _ = app.emit(
                            EVENT_NAME,
                            serde_json::json!({"type": "info", "message": line}),
                        );
                    }
                }
            });
        }

        // Pump stdout → on_pcm callback. Read in fixed-size chunks; the
        // helper writes raw int16 LE so each chunk is a clean sample window.
        tokio::spawn(async move {
            let mut buf = vec![0u8; FRAME_BYTES];
            let mut out = stdout;
            // Carry-over byte if a read returns an odd length (rare but possible
            // because the OS pipe doesn't promise alignment to int16).
            let mut carry: Option<u8> = None;
            loop {
                match out.read(&mut buf).await {
                    Ok(0) => break,
                    Ok(n) => {
                        let mut slice: &[u8] = &buf[..n];
                        let mut pre: Vec<u8> = Vec::new();
                        if let Some(c) = carry.take() {
                            pre.push(c);
                            pre.extend_from_slice(slice);
                            slice = &pre;
                        }
                        if slice.len() % 2 == 1 {
                            carry = Some(*slice.last().unwrap());
                            slice = &slice[..slice.len() - 1];
                        }
                        let samples = mixer::decode_pcm_le(slice);
                        if !samples.is_empty() {
                            on_pcm(samples);
                        }
                    }
                    Err(_) => break,
                }
            }
        });

        let (tx, mut rx) = mpsc::channel::<Cmd>(4);

        // Lifecycle task — closes stdin / kills on stop.
        tokio::spawn(async move {
            // Holding `stdin` keeps the helper from EOF-ing prematurely.
            let mut stdin = Some(stdin);
            while let Some(cmd) = rx.recv().await {
                match cmd {
                    Cmd::Stop(done) => {
                        if let Some(mut s) = stdin.take() {
                            use tokio::io::AsyncWriteExt;
                            let _ = s.write_all(b"stop\n").await;
                            let _ = s.shutdown().await;
                        }
                        let _ = child.wait().await;
                        let _ = done.send(());
                        return;
                    }
                }
            }
            // Sender dropped — kill.
            let _ = child.kill().await;
        });

        Ok(Self { tx })
    }

    pub async fn stop(&self) -> Result<()> {
        let (tx, rx) = oneshot::channel();
        self.tx
            .send(Cmd::Stop(tx))
            .await
            .map_err(|_| anyhow!("system-audio task closed"))?;
        let _ = rx.await;
        Ok(())
    }
}

fn resolve_bin(app: &AppHandle) -> Result<PathBuf> {
    // 1. Explicit override always wins.
    if let Ok(p) = std::env::var("SARATHI_AUDIO_TAP_BIN") {
        return Ok(PathBuf::from(p));
    }

    // 2. Bundled .app: Tauri externalBin places the binary in
    //    Contents/MacOS/<name>-<triple>. tauri::process::current_binary()
    //    points at the main app binary; siblings are alongside.
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let triple_suffixed = dir.join(format!("audio-tap-{}", target_triple()));
            if triple_suffixed.is_file() {
                return Ok(triple_suffixed);
            }
            let plain = dir.join("audio-tap");
            if plain.is_file() {
                return Ok(plain);
            }
        }
    }

    // 3. Resource dir (Tauri 2 exposes app.path().resource_dir()).
    if let Ok(resource_dir) = app.path().resource_dir() {
        for name in ["audio-tap", &format!("audio-tap-{}", target_triple())] {
            let p = resource_dir.join(name);
            if p.is_file() {
                return Ok(p);
            }
        }
    }

    // 4. Dev: walk up from CARGO_MANIFEST_DIR to find the swift build output.
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let candidates = [
        manifest.join("macos/.build/release/audio-tap"),
        manifest.join("macos/.build/apple/Products/Release/audio-tap"),
        manifest.join("macos/.build/debug/audio-tap"),
        manifest.join("macos/.build/apple/Products/Debug/audio-tap"),
        manifest.join(format!("binaries/audio-tap-{}", target_triple())),
    ];
    for c in candidates {
        if c.is_file() {
            return Ok(c);
        }
    }
    Err(anyhow!(
        "audio-tap binary not found. \
        Build it with: bash apps/desktop/src-tauri/macos/build.sh"
    ))
}

/// Compile-time target triple. We can't rely on rustc -vV at runtime, so
/// derive from cfg!. Currently only macOS targets are supported.
fn target_triple() -> &'static str {
    #[cfg(all(target_arch = "aarch64", target_os = "macos"))]
    {
        "aarch64-apple-darwin"
    }
    #[cfg(all(target_arch = "x86_64", target_os = "macos"))]
    {
        "x86_64-apple-darwin"
    }
    #[cfg(not(target_os = "macos"))]
    {
        "unknown"
    }
}

/// Open the macOS Screen Recording privacy pane.
pub fn open_screen_recording_settings() -> Result<()> {
    let url = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture";
    std::process::Command::new("open")
        .arg(url)
        .spawn()
        .map(|_| ())
        .map_err(|e| anyhow!("failed to open System Settings: {}", e))
}
