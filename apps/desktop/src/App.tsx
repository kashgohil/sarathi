import { useCallback, useEffect, useRef, useState } from "react";
import { startMicCapture, type AudioCapture } from "./lib/audio";
import {
  onSidecarEvent,
  onSystemAudioEvent,
  onTrayToggleRecord,
  sendCommand,
  startMixer,
  startSidecar,
  startSystemAudio,
  stopMixer,
  stopSidecar,
  stopSystemAudio,
  type SidecarEvent,
  type SystemAudioEvent,
} from "./lib/sidecar";
import { TranscriptView, type Utterance } from "./components/TranscriptView";
import {
  ReferencesPanel,
  type ReferenceCard,
} from "./components/ReferencesPanel";
import { DocUpload } from "./components/DocUpload";
import { SourceSelector, type AudioSource } from "./components/SourceSelector";
import { PermissionBanner } from "./components/PermissionBanner";
import { FirstRunOverlay } from "./components/FirstRunOverlay";

type Status =
  | { kind: "idle" }
  | { kind: "starting" }
  | { kind: "ready"; stubs: string[] }
  | { kind: "recording"; sessionId: string; source: AudioSource }
  | { kind: "error"; message: string };

export default function App() {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [source, setSource] = useState<AudioSource>("mic");
  const [utterances, setUtterances] = useState<Utterance[]>([]);
  const [cards, setCards] = useState<ReferenceCard[]>([]);
  const [permissionMsg, setPermissionMsg] = useState<string | null>(null);
  // Append-only event log restricted to model_* events. Bounded so it doesn't
  // grow forever during very long sessions.
  const [modelEvents, setModelEvents] = useState<SidecarEvent[]>([]);
  const micRef = useRef<AudioCapture | null>(null);

  // Subscribe to sidecar events.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    (async () => {
      unlisten = await onSidecarEvent(handleEvent);
    })();
    return () => {
      unlisten?.();
    };
  }, []);

  // Subscribe to system-audio helper events (permission, errors).
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    (async () => {
      unlisten = await onSystemAudioEvent(handleSystemAudioEvent);
    })();
    return () => {
      unlisten?.();
    };
  }, []);

  // Tray menu / global hotkey toggle. We capture the latest status via a
  // ref so the listener is registered exactly once but always sees current
  // state when fired.
  const statusRef = useRef(status);
  useEffect(() => {
    statusRef.current = status;
  }, [status]);
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    (async () => {
      unlisten = await onTrayToggleRecord(() => {
        if (statusRef.current.kind === "recording") {
          void stopRecording();
        } else {
          void startRecording();
        }
      });
    })();
    return () => {
      unlisten?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleEvent = useCallback((e: SidecarEvent) => {
    switch (e.type) {
      case "ready":
        setStatus({ kind: "ready", stubs: e.stub_stages });
        break;
      case "utterance":
        setUtterances((prev) => [
          ...prev,
          {
            id: `${e.start_s}-${prev.length}`,
            text: e.text,
            lang: e.lang,
            speaker_id: e.speaker_id,
            start_s: e.start_s,
            end_s: e.end_s,
          },
        ]);
        break;
      case "reference":
        setCards((prev) =>
          [
            {
              id: `ref-${Date.now()}-${prev.length}`,
              trigger: e.trigger,
              query: e.query,
              citations: e.citations,
              receivedAt: Date.now(),
            },
            ...prev,
          ].slice(0, 50),
        );
        break;
      case "answer":
        setCards((prev) => {
          const idx = prev.findIndex((c) => c.trigger === "question" && !c.answer);
          if (idx < 0) return prev;
          const next = [...prev];
          next[idx] = { ...next[idx], answer: e.text };
          return next;
        });
        break;
      case "error":
        // eslint-disable-next-line no-console
        console.warn("sidecar error:", e.message, e.reason);
        break;
      case "log":
        // eslint-disable-next-line no-console
        console.debug("[sidecar stderr]", e.message);
        break;
      case "ingested":
        // eslint-disable-next-line no-console
        console.info(
          `ingested ${e.doc_count} docs, ${e.chunk_count} chunks, indexed=${e.indexed}`,
        );
        break;
      case "model_loading":
      case "model_loaded":
      case "model_error":
        setModelEvents((prev) => {
          const next = [...prev, e];
          return next.length > 200 ? next.slice(-200) : next;
        });
        break;
      default:
        break;
    }
  }, []);

  const handleSystemAudioEvent = useCallback((e: SystemAudioEvent) => {
    if (e.type === "error" && e.kind === "permission_denied") {
      setPermissionMsg(e.message);
    } else if (e.type === "ready") {
      setPermissionMsg(null);
    } else if (e.type === "error") {
      // eslint-disable-next-line no-console
      console.warn("system-audio error:", e.kind, e.message);
    }
  }, []);

  async function ensureSidecar() {
    if (status.kind === "idle" || status.kind === "error") {
      setStatus({ kind: "starting" });
      try {
        await startSidecar();
      } catch (err) {
        setStatus({ kind: "error", message: String(err) });
      }
    }
  }

  async function startRecording() {
    await ensureSidecar();
    const sessionId = `s-${Date.now()}`;
    await sendCommand({
      type: "session",
      action: "start",
      id: sessionId,
      title: new Date().toLocaleString(),
    });

    // Mixer must be started BEFORE the capture sources so their first
    // frames find it and route through it.
    if (source === "both") {
      await startMixer();
    }
    if (source === "mic" || source === "both") {
      micRef.current = await startMicCapture();
    }
    if (source === "system" || source === "both") {
      try {
        await startSystemAudio();
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("startSystemAudio failed:", err);
        setPermissionMsg(String(err));
      }
    }

    setStatus({ kind: "recording", sessionId, source });
  }

  async function stopRecording() {
    await micRef.current?.stop();
    micRef.current = null;
    try {
      await stopSystemAudio();
    } catch {
      /* ignore */
    }
    try {
      await stopMixer();
    } catch {
      /* ignore */
    }
    if (status.kind === "recording") {
      await sendCommand({ type: "session", action: "end", id: status.sessionId });
    }
    setStatus({ kind: "ready", stubs: [] });
  }

  useEffect(() => {
    return () => {
      void micRef.current?.stop();
      void stopSystemAudio().catch(() => {});
      void stopMixer().catch(() => {});
      void stopSidecar();
    };
  }, []);

  const isRecording = status.kind === "recording";

  return (
    <div className="grid grid-rows-[auto_auto_1fr] grid-cols-[1fr_360px] h-screen">
      {/* Top bar */}
      <header className="col-span-2 flex items-center justify-between px-5 py-3 border-b border-neutral-800">
        <div className="flex items-center gap-3">
          <div className="font-medium tracking-tight">Sarathi</div>
          <StatusBadge status={status} />
        </div>
        <div className="flex items-center gap-3">
          <SourceSelector value={source} onChange={setSource} disabled={isRecording} />
          <DocUpload />
          <button
            onClick={isRecording ? stopRecording : startRecording}
            className={
              "px-4 py-1.5 text-sm rounded font-medium " +
              (isRecording
                ? "bg-red-500/90 hover:bg-red-500 text-white"
                : "bg-emerald-500/90 hover:bg-emerald-500 text-neutral-950")
            }
          >
            {isRecording ? "Stop" : "Record"}
          </button>
        </div>
      </header>

      {permissionMsg ? (
        <div className="col-span-2">
          <PermissionBanner message={permissionMsg} />
        </div>
      ) : (
        <div className="col-span-2 h-0" />
      )}

      <main className="overflow-hidden">
        <TranscriptView utterances={utterances} />
      </main>
      <aside className="overflow-hidden">
        <ReferencesPanel cards={cards} />
      </aside>

      <FirstRunOverlay events={modelEvents} />
    </div>
  );
}

function StatusBadge({ status }: { status: Status }) {
  let color = "bg-neutral-700";
  let label = "idle";
  if (status.kind === "starting") {
    color = "bg-amber-500";
    label = "starting";
  } else if (status.kind === "ready") {
    color = status.stubs.length > 0 ? "bg-amber-500" : "bg-emerald-500";
    label = status.stubs.length > 0 ? "ready (stubbed)" : "ready";
  } else if (status.kind === "recording") {
    color = "bg-red-500";
    label = `recording · ${status.source}`;
  } else if (status.kind === "error") {
    color = "bg-red-700";
    label = "error";
  }
  return (
    <div className="flex items-center gap-2 text-xs text-neutral-400">
      <span className={`w-2 h-2 rounded-full ${color}`} />
      <span>{label}</span>
    </div>
  );
}
