use std::sync::Arc;
use tauri::Manager;

mod mixer;
mod sidecar;
mod system_audio;

use mixer::Mixer;
use sidecar::SidecarHandle;
use system_audio::SystemAudioHandle;

#[derive(Default)]
pub struct AppState {
    pub sidecar: parking_lot::Mutex<Option<Arc<SidecarHandle>>>,
    pub system_audio: parking_lot::Mutex<Option<Arc<SystemAudioHandle>>>,
    pub mixer: parking_lot::Mutex<Option<Arc<Mixer>>>,
}

fn make_sidecar_send(app: tauri::AppHandle) -> impl Fn(serde_json::Value) + Send + Sync + 'static {
    move |cmd: serde_json::Value| {
        if let Some(state) = app.try_state::<AppState>() {
            let h = { state.sidecar.lock().clone() };
            if let Some(h) = h {
                // Drop on overload — used for high-rate audio frames.
                let _ = h.try_send(cmd);
            }
        }
    }
}

#[tauri::command]
async fn sidecar_start(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
) -> Result<(), String> {
    let mut guard = state.sidecar.lock();
    if guard.is_some() {
        return Ok(());
    }
    let handle = SidecarHandle::spawn(app.clone()).map_err(|e| e.to_string())?;
    *guard = Some(Arc::new(handle));
    Ok(())
}

#[tauri::command]
async fn sidecar_stop(state: tauri::State<'_, AppState>) -> Result<(), String> {
    let h = { state.sidecar.lock().take() };
    if let Some(h) = h {
        h.shutdown().await.map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn sidecar_send(
    state: tauri::State<'_, AppState>,
    cmd: serde_json::Value,
) -> Result<(), String> {
    let h = { state.sidecar.lock().clone() };
    let h = h.ok_or_else(|| "sidecar not running".to_string())?;
    h.send(cmd).await.map_err(|e| e.to_string())
}

/// Frontend-pushed mic PCM. When the mixer is active, route it through; else
/// forward straight to the sidecar (preserves the single-source mic path).
#[tauri::command]
async fn mic_pcm(
    state: tauri::State<'_, AppState>,
    pcm_b64: String,
) -> Result<(), String> {
    let mixer = { state.mixer.lock().clone() };
    if let Some(m) = mixer {
        let samples = mixer::decode_pcm_b64(&pcm_b64)?;
        m.push_mic(samples);
        return Ok(());
    }
    // Fallback: forward as audio command. Use try_send so a slow Python
    // sidecar drops audio frames rather than back-pressuring the UI.
    let h = { state.sidecar.lock().clone() };
    let h = h.ok_or_else(|| "sidecar not running".to_string())?;
    h.try_send(serde_json::json!({ "type": "audio", "pcm_b64": pcm_b64 }))
        .map(|_| ())
        .map_err(|e| e.to_string())
}

/// Start mixing: subsequent mic PCM goes into the mixer, system-audio pushes
/// itself in. Output is one combined stream to the sidecar.
#[tauri::command]
async fn mixer_start(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
) -> Result<(), String> {
    {
        let g = state.mixer.lock();
        if g.is_some() {
            return Ok(());
        }
    }
    let send = make_sidecar_send(app);
    let m = Mixer::spawn(send);
    *state.mixer.lock() = Some(m);
    Ok(())
}

#[tauri::command]
async fn mixer_stop(state: tauri::State<'_, AppState>) -> Result<(), String> {
    let m = { state.mixer.lock().take() };
    if let Some(m) = m {
        m.stop();
    }
    Ok(())
}

#[tauri::command]
async fn system_audio_start(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
) -> Result<(), String> {
    {
        let guard = state.system_audio.lock();
        if guard.is_some() {
            return Ok(());
        }
    }

    // Choose the destination for system-audio PCM:
    // - if a mixer is running, push raw int16 samples into it;
    // - otherwise, forward directly as `audio` commands to the sidecar via
    //   try_send so we drop on overload instead of stalling the audio thread.
    let app_for_send = app.clone();
    let dest = move |samples: Vec<i16>| {
        let Some(state) = app_for_send.try_state::<AppState>() else {
            return;
        };
        if let Some(m) = state.mixer.lock().clone() {
            m.push_system(samples);
            return;
        }
        let h = { state.sidecar.lock().clone() };
        let Some(h) = h else { return };
        use base64::Engine;
        let mut bytes = Vec::with_capacity(samples.len() * 2);
        for s in &samples {
            bytes.extend_from_slice(&s.to_le_bytes());
        }
        let b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);
        let _ = h.try_send(serde_json::json!({"type": "audio", "pcm_b64": b64}));
    };

    let handle = SystemAudioHandle::spawn(app.clone(), dest).map_err(|e| e.to_string())?;
    *state.system_audio.lock() = Some(Arc::new(handle));
    Ok(())
}

#[tauri::command]
async fn system_audio_stop(state: tauri::State<'_, AppState>) -> Result<(), String> {
    let h = { state.system_audio.lock().take() };
    if let Some(h) = h {
        h.stop().await.map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn open_screen_recording_settings() -> Result<(), String> {
    system_audio::open_screen_recording_settings().map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            sidecar_start,
            sidecar_stop,
            sidecar_send,
            mic_pcm,
            mixer_start,
            mixer_stop,
            system_audio_start,
            system_audio_stop,
            open_screen_recording_settings,
        ])
        .setup(|app| {
            #[cfg(debug_assertions)]
            {
                let window = app.get_webview_window("main").unwrap();
                window.open_devtools();
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
