//! Sidecar bridge: spawn the Python ML process and shuttle NDJSON between
//! it and the Tauri frontend.
//!
//! In dev: invokes `uv run sarathi serve` from the sidecar package directory.
//! In release (M5): will invoke a bundled PyInstaller binary at a known path
//! relative to the .app bundle. For now we resolve via env var or repo layout.

use anyhow::{anyhow, Context, Result};
use serde_json::Value;
use std::path::PathBuf;
use std::process::Stdio;
use tauri::{AppHandle, Emitter};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, Command};
use tokio::sync::{mpsc, oneshot};

/// Events emitted to the frontend. We just forward whatever the sidecar
/// produces; the frontend filters by `type`.
const EVENT_NAME: &str = "sidecar://event";

pub struct SidecarHandle {
    tx: mpsc::Sender<SidecarMsg>,
}

enum SidecarMsg {
    Send(Value),
    Shutdown(oneshot::Sender<()>),
}

impl SidecarHandle {
    pub fn spawn(app: AppHandle) -> Result<Self> {
        let (program, args, cwd) = resolve_command()?;

        let mut cmd = Command::new(&program);
        cmd.args(&args)
            .current_dir(&cwd)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);

        let mut child: Child = cmd.spawn().with_context(|| {
            format!("spawning sidecar: {} {:?} (cwd={})", program, args, cwd.display())
        })?;

        let stdin = child.stdin.take().ok_or_else(|| anyhow!("no stdin"))?;
        let stdout = child.stdout.take().ok_or_else(|| anyhow!("no stdout"))?;
        let stderr = child.stderr.take().ok_or_else(|| anyhow!("no stderr"))?;

        let (tx, rx) = mpsc::channel::<SidecarMsg>(256);

        // Pump stdout → frontend events.
        {
            let app = app.clone();
            tokio::spawn(async move {
                let mut lines = BufReader::new(stdout).lines();
                loop {
                    match lines.next_line().await {
                        Ok(Some(line)) => {
                            if let Ok(v) = serde_json::from_str::<Value>(&line) {
                                let _ = app.emit(EVENT_NAME, v);
                            } else {
                                // Forward non-JSON lines as raw error events so
                                // they're never silently dropped.
                                let _ = app.emit(
                                    EVENT_NAME,
                                    serde_json::json!({"type": "error", "message": line}),
                                );
                            }
                        }
                        Ok(None) => break,
                        Err(_) => break,
                    }
                }
            });
        }

        // Pump stderr → frontend as error events. The Python side uses rich
        // to write diagnostics here; surfacing them avoids silent failures.
        {
            let app = app.clone();
            tokio::spawn(async move {
                let mut lines = BufReader::new(stderr).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    let _ = app.emit(
                        EVENT_NAME,
                        serde_json::json!({"type": "log", "stream": "stderr", "message": line}),
                    );
                }
            });
        }

        // Writer task: serializes commands to the sidecar's stdin, awaits
        // shutdown when asked.
        tokio::spawn(writer_loop(child, stdin, rx));

        Ok(Self { tx })
    }

    pub async fn send(&self, cmd: Value) -> Result<()> {
        self.tx
            .send(SidecarMsg::Send(cmd))
            .await
            .map_err(|_| anyhow!("sidecar writer closed"))
    }

    /// Drop-on-full variant for high-volume paths (audio frames). Returns
    /// `Ok(true)` if queued, `Ok(false)` if dropped because the writer is
    /// behind, `Err` if the writer is gone.
    pub fn try_send(&self, cmd: Value) -> Result<bool> {
        use tokio::sync::mpsc::error::TrySendError;
        match self.tx.try_send(SidecarMsg::Send(cmd)) {
            Ok(()) => Ok(true),
            Err(TrySendError::Full(_)) => Ok(false),
            Err(TrySendError::Closed(_)) => Err(anyhow!("sidecar writer closed")),
        }
    }

    pub async fn shutdown(&self) -> Result<()> {
        let (done_tx, done_rx) = oneshot::channel();
        self.tx
            .send(SidecarMsg::Shutdown(done_tx))
            .await
            .map_err(|_| anyhow!("sidecar writer closed"))?;
        let _ = done_rx.await;
        Ok(())
    }
}

async fn writer_loop(mut child: Child, mut stdin: ChildStdin, mut rx: mpsc::Receiver<SidecarMsg>) {
    while let Some(msg) = rx.recv().await {
        match msg {
            SidecarMsg::Send(v) => {
                let line = match serde_json::to_string(&v) {
                    Ok(s) => s,
                    Err(_) => continue,
                };
                if stdin.write_all(line.as_bytes()).await.is_err() {
                    break;
                }
                if stdin.write_all(b"\n").await.is_err() {
                    break;
                }
                let _ = stdin.flush().await;
            }
            SidecarMsg::Shutdown(done) => {
                // Send the cooperative shutdown command first.
                let _ = stdin.write_all(b"{\"type\":\"shutdown\"}\n").await;
                let _ = stdin.flush().await;
                drop(stdin);
                let _ = child.wait().await;
                let _ = done.send(());
                return;
            }
        }
    }
    // Channel closed without explicit shutdown — kill the child.
    let _ = child.kill().await;
}

/// Resolve which command to spawn for the sidecar.
///
/// Priority:
///  1. `SARATHI_SIDECAR_BIN` env var (path to a built sidecar binary).
///  2. Bundled .app: a triple-suffixed `sarathi-sidecar-<triple>` next to
///     the main app binary.
///  3. `SARATHI_SIDECAR_CWD` env var → `uv run sarathi serve`.
///  4. Default: walk up from CARGO_MANIFEST_DIR to find `apps/sidecar`,
///     spawn `uv run sarathi serve` there.
fn resolve_command() -> Result<(String, Vec<String>, PathBuf)> {
    if let Ok(bin) = std::env::var("SARATHI_SIDECAR_BIN") {
        let path = PathBuf::from(bin);
        let cwd = path.parent().map(PathBuf::from).unwrap_or_else(|| ".".into());
        return Ok((path.display().to_string(), vec!["serve".into()], cwd));
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for name in [
                format!("sarathi-sidecar-{}", target_triple()),
                "sarathi-sidecar".to_string(),
            ] {
                let candidate = dir.join(&name);
                if candidate.is_file() {
                    return Ok((
                        candidate.display().to_string(),
                        vec!["serve".into()],
                        dir.to_path_buf(),
                    ));
                }
            }
        }
    }

    let cwd = if let Ok(v) = std::env::var("SARATHI_SIDECAR_CWD") {
        PathBuf::from(v)
    } else {
        find_sidecar_dir()?
    };

    Ok((
        "uv".into(),
        vec![
            "run".into(),
            "--project".into(),
            cwd.display().to_string(),
            "sarathi".into(),
            "serve".into(),
        ],
        cwd,
    ))
}

fn find_sidecar_dir() -> Result<PathBuf> {
    // CARGO_MANIFEST_DIR is set at build time; available at runtime in dev.
    let start = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let mut cur = start.clone();
    for _ in 0..6 {
        let candidate = cur.join("apps").join("sidecar");
        if candidate.is_dir() {
            return Ok(candidate);
        }
        if !cur.pop() {
            break;
        }
    }
    Err(anyhow!(
        "could not locate apps/sidecar from {}",
        start.display()
    ))
}

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
