import { useEffect, useState } from "react";
import { Wheel } from "./Wheel";
import {
  onSidecarEvent,
  sendCommand,
  startSidecar,
  type SidecarEvent,
} from "../lib/sidecar";

/**
 * First-launch setup screen.
 *
 * Mounts in place of the main UI when `localStorage["sarathi.setupComplete"]`
 * is unset. Sends a `preload` command to the sidecar to download all the
 * required ML models, then shows live per-model progress driven by the
 * sidecar's `model_loading` / `model_loaded` events.
 *
 * Until every required component reports `loaded`, the user can't reach the
 * main app — that's the point: a recording session without these models
 * downloaded would silently produce stub output.
 *
 * Optional escape: a faded "Skip for now" link in the corner. Useful in
 * dev (ml extras not installed) or if a network-flaky download keeps
 * failing — tells App.tsx to flip the flag and let the user through.
 */

type ComponentKey = "asr.vad" | "asr.whisper" | "embed.bge_m3" | "llm.mlx";

type Row = {
  key: ComponentKey;
  label: string;
  size: string;
  status: "pending" | "loading" | "done" | "error";
  errorMessage?: string;
  startedAt?: number;
  finishedAt?: number;
};

// What we render on screen. The keys must match the `component` strings the
// sidecar emits in `model_loading` / `model_loaded`. The Python `loading()`
// context manager in `sarathi.progress` owns the source-of-truth strings.
const COMPONENTS: Omit<Row, "status">[] = [
  { key: "asr.vad", label: "Silero VAD · utterance detection", size: "≈ 2 MB" },
  { key: "asr.whisper", label: "Whisper · transcription", size: "≈ 1 GB" },
  {
    key: "embed.bge_m3",
    label: "BGE-M3 · multilingual retrieval",
    size: "≈ 2.3 GB",
  },
  { key: "llm.mlx", label: "Qwen 2.5 · answer generation", size: "≈ 4 GB" },
];

type Phase = "booting" | "ready" | "running" | "complete" | "failed";

export function Setup({
  onDone,
  onSkip,
}: {
  onDone: () => void;
  onSkip: () => void;
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    COMPONENTS.map((c) => ({ ...c, status: "pending" })),
  );
  const [phase, setPhase] = useState<Phase>("booting");
  const [now, setNow] = useState<number>(Date.now());

  // Tick for elapsed-time labels on the loading row.
  useEffect(() => {
    if (phase !== "running") return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [phase]);

  // Boot the sidecar and listen for events.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let cancelled = false;

    (async () => {
      try {
        await startSidecar();
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn("startSidecar failed:", e);
      }
      unlisten = await onSidecarEvent((e) => {
        if (cancelled) return;
        handle(e);
      });
    })();

    return () => {
      cancelled = true;
      unlisten?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handle(e: SidecarEvent) {
    switch (e.type) {
      case "ready":
        setPhase((p) => (p === "booting" ? "ready" : p));
        break;
      case "model_loading":
        setRows((rs) =>
          rs.map((r) =>
            r.key === e.component
              ? { ...r, status: "loading", startedAt: Date.now() }
              : r,
          ),
        );
        break;
      case "model_loaded":
        setRows((rs) =>
          rs.map((r) =>
            r.key === e.component
              ? { ...r, status: "done", finishedAt: Date.now() }
              : r,
          ),
        );
        break;
      case "model_error":
        setRows((rs) =>
          rs.map((r) =>
            r.key === e.component
              ? {
                  ...r,
                  status: "error",
                  errorMessage: e.error,
                  finishedAt: Date.now(),
                }
              : r,
          ),
        );
        break;
      case "preload_done":
        setPhase(e.ok ? "complete" : "failed");
        break;
      default:
        break;
    }
  }

  function begin() {
    setPhase("running");
    void sendCommand({
      type: "preload",
      components: ["asr", "embed", "llm"],
    });
  }

  return (
    <div className="fixed inset-0 z-[90] bg-night text-page flex flex-col items-center justify-center px-8">
      {/* Top zone matches the main app's traffic-light nest so the chrome
          flow stays consistent. */}
      <div
        className="absolute top-0 inset-x-0 h-9"
        data-tauri-drag-region
      />

      <div className="w-full max-w-[640px]">
        {/* Brand mark */}
        <div className="flex items-center gap-3 mb-10">
          <Wheel size={26} className="text-flame-ember" />
          <span className="font-display text-[1.3rem] text-page">Sarathi</span>
        </div>

        {/* Headline */}
        <h1 className="font-display font-light text-[clamp(2rem,5vw,3.4rem)] leading-[0.96] text-page">
          {phase === "complete" ? (
            <>
              Ready to <span className="italicize text-flame-ember">begin</span>.
            </>
          ) : phase === "failed" ? (
            <>
              Something didn't <span className="italicize text-flame-ember">finish</span>.
            </>
          ) : (
            <>
              First, the <span className="italicize text-flame-ember">setup</span>.
            </>
          )}
        </h1>

        <p className="mt-6 text-[14.5px] leading-[1.6] text-page-dim max-w-[58ch]">
          {phase === "complete"
            ? "Models are on your machine and ready. Nothing leaves your computer from now on."
            : phase === "failed"
              ? "Some components didn't load. You can retry the failed ones, or continue and let them retry on demand."
              : "We need to download the models that will run on your Mac. They live on your disk after this and never leave your computer."}
        </p>

        {/* Component list */}
        <ol className="mt-10 border-t border-b border-page-rule divide-y divide-page-rule">
          {rows.map((r) => (
            <li
              key={r.key}
              className="grid grid-cols-[1rem_1fr_auto_auto] items-center gap-4 py-3.5"
            >
              <Dot status={r.status} />
              <div className="min-w-0">
                <div className="text-[13.5px] text-page truncate">{r.label}</div>
                {r.errorMessage ? (
                  <div className="text-[11px] text-sindoor truncate mt-0.5">
                    {r.errorMessage}
                  </div>
                ) : (
                  <div className="font-mono text-[10.5px] uppercase tracking-wider2 text-page-ghost truncate">
                    {r.key}
                  </div>
                )}
              </div>
              <span className="font-mono text-[10.5px] tabular-nums text-page-ghost">
                {r.size}
              </span>
              <span
                className={
                  "font-mono text-[10.5px] tabular-nums " +
                  (r.status === "loading"
                    ? "text-flame"
                    : r.status === "error"
                      ? "text-sindoor"
                      : "text-page-ghost")
                }
              >
                {statusLabel(r, now)}
              </span>
            </li>
          ))}
        </ol>

        {/* Footer */}
        <div className="mt-10 flex items-center justify-between gap-6">
          <button
            onClick={onSkip}
            className="font-mono text-[10.5px] uppercase tracking-wider2 text-page-ghost hover:text-page transition"
          >
            Skip for now
          </button>

          {phase === "ready" && (
            <button
              onClick={begin}
              className="bg-flame text-night-deep px-6 py-3 text-[13.5px] font-medium tracking-tight rounded-full hover:bg-flame-ember transition"
            >
              Begin setup
            </button>
          )}

          {phase === "booting" && (
            <span className="font-mono text-[10.5px] uppercase tracking-wider2 text-page-ghost">
              starting…
            </span>
          )}

          {phase === "running" && (
            <span className="font-mono text-[10.5px] uppercase tracking-wider2 text-flame">
              downloading
            </span>
          )}

          {phase === "complete" && (
            <button
              onClick={onDone}
              className="bg-flame text-night-deep px-6 py-3 text-[13.5px] font-medium tracking-tight rounded-full hover:bg-flame-ember transition"
            >
              Continue
            </button>
          )}

          {phase === "failed" && (
            <div className="flex items-center gap-3">
              <button
                onClick={begin}
                className="border border-page/30 text-page px-4 py-2 text-[12.5px] tracking-tight rounded-full hover:bg-page/10 transition"
              >
                Retry
              </button>
              <button
                onClick={onDone}
                className="bg-flame text-night-deep px-6 py-3 text-[13.5px] font-medium tracking-tight rounded-full hover:bg-flame-ember transition"
              >
                Continue anyway
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Dot({ status }: { status: Row["status"] }) {
  const color =
    status === "loading"
      ? "bg-flame animate-pulse"
      : status === "done"
        ? "bg-flame-ember"
        : status === "error"
          ? "bg-sindoor"
          : "bg-page/25";
  return <span className={`w-2 h-2 rounded-full ${color}`} />;
}

function statusLabel(r: Row, now: number): string {
  if (r.status === "pending") return "·";
  if (r.status === "loading") {
    const elapsed = Math.max(0, Math.floor((now - (r.startedAt ?? now)) / 1000));
    return `${elapsed}s`;
  }
  if (r.status === "done") {
    const elapsed = Math.max(
      0,
      Math.floor(((r.finishedAt ?? 0) - (r.startedAt ?? 0)) / 1000),
    );
    return `${elapsed}s ✓`;
  }
  return "error";
}
