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
import { Wheel } from "./components/Wheel";
import { Splash } from "./components/Splash";
import { Setup } from "./components/Setup";

const SETUP_DONE_KEY = "sarathi.setupComplete";

type Status =
  | { kind: "idle" }
  | { kind: "starting" }
  | { kind: "ready"; stubs: string[] }
  | { kind: "recording"; sessionId: string; source: AudioSource }
  | { kind: "error"; message: string };

export default function App() {
  // Splash plays once per process; if we re-mount the App during dev HMR
  // we still want a single fresh launch experience, which is the default.
  const [splashDone, setSplashDone] = useState(false);
  // Setup gate: until `localStorage.sarathi.setupComplete = "true"` we block
  // access to the main app and show the Setup view. The flag gets set after
  // a successful preload (or after the user clicks "Continue anyway").
  /** Toggle for re-opening the Setup screen as a manage-models view from
   *  the header. Only meaningful after first-run setup is complete. */
  const [manageModelsOpen, setManageModelsOpen] = useState<boolean>(false);
  const [setupNeeded, setSetupNeeded] = useState<boolean>(() => {
    try {
      return localStorage.getItem(SETUP_DONE_KEY) !== "true";
    } catch {
      return true;
    }
  });
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
    <div className="grid grid-rows-[auto_auto_auto_1fr] grid-cols-[1fr_360px] h-screen">
      {/* macOS traffic-light nest. The window has `titleBarStyle: Overlay`,
          so the system buttons float over this transparent drag zone. The
          taller height gives a comfortable grab-target. */}
      <div
        className="col-span-2 h-9 bg-night"
        data-tauri-drag-region
      />

      {/* App header — also a drag region so the user can grab the window
          from anywhere along the top, like every other macOS app. Buttons
          and inputs inside still receive their own clicks. */}
      <header
        className="col-span-2 flex items-center justify-between px-5 pt-2 pb-3 border-b border-page-rule"
        data-tauri-drag-region
      >
        {/* Drag region must be explicit on the inner flex clusters too —
            Tauri 2's drag-region inheritance through nested flex containers
            isn't reliable, so we tag every non-interactive wrapper. The
            brand mark, the wordmark, and the status badge are all
            draggable; the controls cluster on the right contains buttons
            and selects which automatically opt out. */}
        <div className="flex items-center gap-3" data-tauri-drag-region>
          <Wheel size={22} className="text-flame-ember" />
          <div className="font-display text-[1.2rem] text-page">Sarathi</div>
          <StatusBadge status={status} />
        </div>
        <div className="flex items-center gap-3">
          {/* Re-open the Setup screen for reviewing / re-downloading
              models. Disabled while recording so we don't yank the
              audio path out from under an active session. */}
          <button
            onClick={() => setManageModelsOpen(true)}
            disabled={isRecording}
            className="text-[12.5px] tracking-tight text-page-dim hover:text-page disabled:opacity-50 transition"
            title="Manage downloaded models"
          >
            Models
          </button>
          <SourceSelector value={source} onChange={setSource} disabled={isRecording} />
          <DocUpload />
          <button
            onClick={isRecording ? stopRecording : startRecording}
            className={
              "px-4 py-1.5 text-[12.5px] tracking-tight rounded-full font-medium transition " +
              (isRecording
                ? "bg-sindoor hover:bg-sindoor-deep text-page"
                : "bg-flame hover:bg-flame-ember text-night-deep")
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

      {/* Setup gate: mounts as soon as we know the user needs it (not gated
          on splashDone) so it sits *underneath* the splash from frame 0.
          When splash fades out, what's revealed is Setup, never the main
          UI — no flash of unset content. Sidecar boots inside Setup's
          mount effect, so by the time splash dismisses, the sidecar may
          already be in `ready`. Setup is mandatory: the only exit is the
          Continue button, which is disabled until every required model
          is downloaded. */}
      {setupNeeded && (
        <Setup
          mode="setup"
          onDismiss={() => {
            try {
              localStorage.setItem(SETUP_DONE_KEY, "true");
            } catch {
              /* ignore: e.g., storage unavailable in some webviews */
            }
            setSetupNeeded(false);
          }}
        />
      )}

      {/* Manage-models view: same Setup component, "manage" mode. Opened
          from the header's Models button after first-run setup is done.
          Always dismissable via Close. */}
      {!setupNeeded && manageModelsOpen && (
        <Setup
          mode="manage"
          onDismiss={() => setManageModelsOpen(false)}
        />
      )}

      {!splashDone && <Splash onDone={() => setSplashDone(true)} />}
    </div>
  );
}

function StatusBadge({ status }: { status: Status }) {
  let color = "bg-page/30";
  let label = "idle";
  if (status.kind === "starting") {
    color = "bg-flame";
    label = "starting";
  } else if (status.kind === "ready") {
    color = status.stubs.length > 0 ? "bg-flame" : "bg-flame-ember";
    label = status.stubs.length > 0 ? "ready (stubbed)" : "ready";
  } else if (status.kind === "recording") {
    color = "bg-sindoor";
    label = `recording · ${status.source}`;
  } else if (status.kind === "error") {
    color = "bg-sindoor-deep";
    label = "error";
  }
  return (
    <div className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-wider2 text-page-ghost ml-2">
      <span className={`w-1.5 h-1.5 rounded-full ${color}`} />
      <span>{label}</span>
    </div>
  );
}
