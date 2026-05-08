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
      session_id: string | null;
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
  | { type: "error"; message: string; reason?: string };

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

export async function onSidecarEvent(
  handler: (e: SidecarEvent) => void,
): Promise<UnlistenFn> {
  return listen<SidecarEvent>(EVENT_NAME, (evt) => handler(evt.payload));
}
