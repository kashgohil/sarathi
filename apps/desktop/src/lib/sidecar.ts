import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

/** All possible event types emitted by the sidecar via the Rust bridge. */
export type SidecarEvent =
  | { type: "ready"; version: string; stub_stages: string[] }
  | {
      type: "utterance";
      text: string;
      start_s: number;
      end_s: number;
      lang: string | null;
      speaker_id: string | null;
      session_id: string | null;
    }
  | {
      type: "vacuumed";
      deleted_transcripts: number;
      retention_days: number;
    }
  | {
      type: "question";
      tier: "heuristic" | "llm";
      text: string;
      confidence: number;
      reason: string;
      query: string;
    }
  | {
      type: "reference";
      trigger: "question" | "proactive";
      query: string;
      citations: Citation[];
    }
  | { type: "answer"; text: string; citations: Citation[]; model?: string }
  | {
      type: "ingested";
      doc_count: number;
      chunk_count: number;
      indexed: boolean;
      reason: string | null;
    }
  | { type: "log"; stream: "stderr"; message: string }
  | { type: "error"; message: string; reason?: string }
  | {
      type: "model_loading";
      component: string;
      label: string;
      approx_mb: number | null;
    }
  | {
      type: "model_loaded";
      component: string;
      label: string;
      elapsed_ms: number;
    }
  | {
      type: "model_error";
      component: string;
      label: string;
      error: string;
      elapsed_ms: number;
    }
  | {
      type: "preload_done";
      components: Record<string, boolean>;
      ok: boolean;
    };

export type Citation = {
  chunk_id: string;
  text: string;
  lang: string | null;
  source: string | null;
  page: number | null;
  score: number;
};

/** Commands that can be sent to the sidecar. */
export type SidecarCommand =
  | { type: "audio"; pcm_b64: string }
  | { type: "ingest"; path: string }
  | { type: "question"; text: string }
  | { type: "session"; action: "start" | "end"; id: string; title?: string }
  | { type: "preload"; components?: string[] }
  | { type: "shutdown" };

const EVENT_NAME = "sidecar://event";

export async function startSidecar(): Promise<void> {
  await invoke("sidecar_start");
}

export async function stopSidecar(): Promise<void> {
  await invoke("sidecar_stop");
}

export async function sendCommand(cmd: SidecarCommand): Promise<void> {
  await invoke("sidecar_send", { cmd });
}

/** Mic PCM frames go through this path so the Rust side can route them
 * through the mixer (when "Mic + system" is active) or forward directly
 * to the sidecar otherwise. Always uses try_send semantics — frames may
 * be dropped if the sidecar is overloaded. */
export async function sendMicPcm(pcm_b64: string): Promise<void> {
  await invoke("mic_pcm", { pcmB64: pcm_b64 });
}

export async function startMixer(): Promise<void> {
  await invoke("mixer_start");
}

export async function stopMixer(): Promise<void> {
  await invoke("mixer_stop");
}

export async function onSidecarEvent(
  handler: (e: SidecarEvent) => void,
): Promise<UnlistenFn> {
  return listen<SidecarEvent>(EVENT_NAME, (evt) => handler(evt.payload));
}

// ---------------------------------------------------------------------------
// System audio (macOS ScreenCaptureKit helper)
// ---------------------------------------------------------------------------

export type SystemAudioEvent =
  | { type: "ready" }
  | { type: "info"; message: string }
  | {
      type: "error";
      kind: "permission_denied" | "init" | "start_failed" | "stream_error";
      message: string;
    };

const SYSTEM_AUDIO_EVENT = "system-audio://event";

export async function startSystemAudio(): Promise<void> {
  await invoke("system_audio_start");
}

export async function stopSystemAudio(): Promise<void> {
  await invoke("system_audio_stop");
}

export async function openScreenRecordingSettings(): Promise<void> {
  await invoke("open_screen_recording_settings");
}

export async function onSystemAudioEvent(
  handler: (e: SystemAudioEvent) => void,
): Promise<UnlistenFn> {
  return listen<SystemAudioEvent>(SYSTEM_AUDIO_EVENT, (evt) => handler(evt.payload));
}

// ---------------------------------------------------------------------------
// Tray + global hotkey
// ---------------------------------------------------------------------------

export async function onTrayToggleRecord(handler: () => void): Promise<UnlistenFn> {
  return listen("tray://toggle-record", () => handler());
}
