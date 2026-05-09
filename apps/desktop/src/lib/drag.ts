import { getCurrentWindow } from "@tauri-apps/api/window";

/**
 * Manual window-drag handler.
 *
 * Tauri 2 *does* ship a `data-tauri-drag-region` attribute and an
 * automatic mousedown listener, but the auto-detection runs through a
 * MutationObserver that races React's commit phase. In our app the
 * dragged DOM is rendered (and re-rendered) by React after Tauri has
 * already attached its observers, so the attribute often goes unseen.
 *
 * Fix: install a single, persistent mousedown listener at the document
 * level. On every press, walk up from the event target until we either:
 *   - hit an element that opts itself out of drag (a button, link,
 *     input, select, textarea, label, or anything explicitly tagged
 *     with `data-no-drag-region`), in which case we let the native
 *     click happen, OR
 *   - hit an element with `data-tauri-drag-region`, in which case we
 *     call the Tauri window's `startDragging()` and stop walking.
 *
 * Set up once at app boot in `main.tsx`. Cheap — one global listener.
 */

const INTERACTIVE = new Set([
  "BUTTON",
  "A",
  "INPUT",
  "SELECT",
  "TEXTAREA",
  "LABEL",
]);

export function installWindowDrag(): void {
  // Only install in a Tauri context. In Vite preview / browser dev,
  // `getCurrentWindow()` would throw on call.
  if (typeof window === "undefined") return;
  if (!("__TAURI_INTERNALS__" in window)) return;

  document.addEventListener("mousedown", (e: MouseEvent) => {
    if (e.button !== 0) return;

    let el = e.target as HTMLElement | null;
    while (el && el !== document.body) {
      // First interactive ancestor wins — bail out, let native click fire.
      if (INTERACTIVE.has(el.tagName)) return;
      if (el.hasAttribute("data-no-drag-region")) return;

      if (el.hasAttribute("data-tauri-drag-region")) {
        // Found a drag region. Defer to Tauri's native window drag.
        e.preventDefault();
        void getCurrentWindow().startDragging();
        return;
      }
      el = el.parentElement;
    }
  });
}
