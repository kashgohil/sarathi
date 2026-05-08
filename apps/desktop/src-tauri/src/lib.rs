use std::sync::Arc;
use tauri::Manager;

mod sidecar;

use sidecar::SidecarHandle;

#[derive(Default)]
pub struct AppState {
    pub sidecar: parking_lot::Mutex<Option<Arc<SidecarHandle>>>,
}

#[tauri::command]
async fn sidecar_start(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
) -> Result<(), String> {
    let mut guard = state.sidecar.lock();
    if guard.is_some() {
        return Ok(()); // already running
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
