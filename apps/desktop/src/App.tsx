import { useCallback, useEffect, useRef, useState } from "react";
import { startMicCapture, type AudioCapture } from "./lib/audio";
import {
  onSidecarEvent,
  sendCommand,
  startSidecar,
  stopSidecar,
  type SidecarEvent,
} from "./lib/sidecar";
import { TranscriptView, type Utterance } from "./components/TranscriptView";
import {
  ReferencesPanel,
  type ReferenceCard,
} from "./components/ReferencesPanel";
import { DocUpload } from "./components/DocUpload";

type Status =
  | { kind: "idle" }
  | { kind: "starting" }
  | { kind: "ready"; stubs: string[] }
  | { kind: "recording"; sessionId: string }
  | { kind: "error"; message: string };

export default function App() {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [utterances, setUtterances] = useState<Utterance[]>([]);
  const [cards, setCards] = useState<ReferenceCard[]>([]);
  const captureRef = useRef<AudioCapture | null>(null);

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
            start_s: e.start_s,
            end_s: e.end_s,
          },
        ]);
        break;
      case "reference":
        setCards((prev) => [
          {
            id: `ref-${Date.now()}-${prev.length}`,
            trigger: e.trigger,
            query: e.query,
            citations: e.citations,
            receivedAt: Date.now(),
          },
          ...prev,
        ].slice(0, 50));
        break;
      case "answer":
        setCards((prev) => {
          // Attach answer to the most recent question-triggered card.
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
      default:
        break;
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
    captureRef.current = await startMicCapture();
    setStatus({ kind: "recording", sessionId });
  }

  async function stopRecording() {
    await captureRef.current?.stop();
    captureRef.current = null;
    if (status.kind === "recording") {
      await sendCommand({ type: "session", action: "end", id: status.sessionId });
    }
    setStatus({ kind: "ready", stubs: [] });
  }

  useEffect(() => {
    return () => {
      void captureRef.current?.stop();
      void stopSidecar();
    };
  }, []);

  const isRecording = status.kind === "recording";

  return (
    <div className="grid grid-rows-[auto_1fr] grid-cols-[1fr_360px] h-screen">
      {/* Top bar */}
      <header className="col-span-2 flex items-center justify-between px-5 py-3 border-b border-neutral-800">
        <div className="flex items-center gap-3">
          <div className="font-medium tracking-tight">Sarathi</div>
          <StatusBadge status={status} />
        </div>
        <div className="flex items-center gap-3">
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

      {/* Main: transcript */}
      <main className="overflow-hidden">
        <TranscriptView utterances={utterances} />
      </main>

      {/* Side: references */}
      <aside className="overflow-hidden">
        <ReferencesPanel cards={cards} />
      </aside>
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
    label = "recording";
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
