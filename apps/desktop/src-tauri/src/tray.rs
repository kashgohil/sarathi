//! Menu-bar tray icon and global hotkey.
//!
//! Tray menu:
//!   - Toggle Recording   (also bound to Cmd+Shift+R)
//!   - Show Sarathi
//!   - Quit
//!
//! Both the tray click and the global hotkey emit a `tray://toggle-record`
//! event to the frontend. The renderer owns the actual recording state, so
//! this module never tries to guess whether we're currently recording — it
//! just tells the renderer to flip.

use tauri::image::Image;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

/// Black-on-transparent wheel, sized for the macOS menu bar. Embedded at
/// compile time so we don't depend on a runtime file path.
const TRAY_ICON_BYTES: &[u8] = include_bytes!("../icons/tray.png");

pub const EVENT_TOGGLE_RECORD: &str = "tray://toggle-record";

/// Cmd+Shift+R on macOS, Ctrl+Shift+R elsewhere.
fn record_hotkey() -> Shortcut {
    let mods = if cfg!(target_os = "macos") {
        Modifiers::SUPER | Modifiers::SHIFT
    } else {
        Modifiers::CONTROL | Modifiers::SHIFT
    };
    Shortcut::new(Some(mods), Code::KeyR)
}

pub fn install(app: &AppHandle) -> tauri::Result<()> {
    install_tray(app)?;
    install_hotkey(app)?;
    Ok(())
}

fn install_tray(app: &AppHandle) -> tauri::Result<()> {
    let toggle = MenuItem::with_id(app, "toggle", "Toggle Recording", true, Some("Cmd+Shift+R"))?;
    let show = MenuItem::with_id(app, "show", "Show Sarathi", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, Some("Cmd+Q"))?;
    let menu = Menu::with_items(app, &[&toggle, &show, &quit])?;

    // Tray icon: a pure-white wheel embedded as a regular (non-template)
    // image, so macOS leaves the colour alone. Reads white on the standard
    // dark menu bar; if the user runs a light menu bar they can ask us to
    // ship a template variant.
    let tray_image = Image::from_bytes(TRAY_ICON_BYTES)
        .unwrap_or_else(|_| Image::new_owned(vec![0; 4], 1, 1));

    let _ = TrayIconBuilder::with_id("sarathi-tray")
        .tooltip("Sarathi")
        .icon(tray_image)
        .menu(&menu)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "toggle" => {
                let _ = app.emit(EVENT_TOGGLE_RECORD, ());
            }
            "show" => {
                show_main(app);
            }
            "quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // Left-click on macOS shows menu automatically; on Windows/Linux
            // we treat it as "show window".
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main(tray.app_handle());
            }
        })
        .build(app)?;

    Ok(())
}

fn install_hotkey(app: &AppHandle) -> tauri::Result<()> {
    let plugin = app.global_shortcut();
    let hk = record_hotkey();

    plugin
        .on_shortcut(hk, move |app, _shortcut, event| {
            if event.state() == ShortcutState::Pressed {
                let _ = app.emit(EVENT_TOGGLE_RECORD, ());
            }
        })
        .map_err(|e| tauri::Error::Anyhow(anyhow::anyhow!(e.to_string())))?;
    Ok(())
}

fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
}
