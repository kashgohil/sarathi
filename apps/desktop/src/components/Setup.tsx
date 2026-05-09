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
 * is unset. The user downloads each capability separately via per-row
 * "Download" buttons; the sidecar's `preload` command takes a list of
 * components and we dispatch one component per row.
 *
 * Until every required capability reports `ready`, the user can't reach
 * the main app — that's the point: a recording session without these
 * models would silently produce stub output.
 */

type Capability = "asr" | "embed" | "llm";
type RowStatus = "pending" | "loading" | "done" | "error";

type Row = {
  capability: Capability;
  /** model_loading event `component` strings that belong to this row. */
  modelKeys: readonly string[];
  /** Lead with the *need* — what this enables for the user. */
  need: string;
  /** Plain-language description of what the capability does. */
  detail: string;
  /** The actual model name + size, in mono small caps. */
  meta: string;
  /** Stable, declared-upfront target download size for this capability.
   *  Used as the denominator for percent so the bar climbs
   *  monotonically — observed totals from tqdm grow as new files
   *  register, which would otherwise drag the percentage backwards. */
  approxBytes: number;
  status: RowStatus;
  errorMessage?: string;
  /** Per-row timing, used for "Xs" / "Xs ✓" labels. */
  startedAt?: number;
  finishedAt?: number;
  /** Per-model load tracking so a multi-model row only flips to `done`
   *  after every member has loaded. */
  modelStates: Record<string, "pending" | "loading" | "done" | "error">;
  /** Per-model byte counters so a multi-model row gets a real,
   *  bytes-weighted percent — important for `asr`, where Whisper is
   *  ~1 GB and Silero VAD is ~2 MB; a naive average would be misleading. */
  bytes: Record<string, { current: number; total: number }>;
};

const ROWS: Omit<
  Row,
  "status" | "modelStates" | "startedAt" | "finishedAt" | "bytes"
>[] = [
  {
    capability: "asr",
    modelKeys: ["asr.vad", "asr.whisper"],
    need: "Hears your conversations",
    detail:
      "Picks up speech from your mic or system audio (Zoom, Meet, Teams) and writes it down in real time, in any language you speak.",
    meta: "Silero VAD + Whisper large-v3-turbo · ≈ 1 GB",
    approxBytes: 1_000 * 1024 * 1024,
  },
  {
    capability: "embed",
    modelKeys: ["embed.bge_m3"],
    need: "Reads your documents",
    detail:
      "Indexes the PDFs, scans, and notes you upload so the right page is one query away — even when the question and the source are in different languages.",
    meta: "BGE-M3 multilingual embeddings · ≈ 2.3 GB",
    approxBytes: 2_300 * 1024 * 1024,
  },
  {
    capability: "llm",
    modelKeys: ["llm.mlx"],
    need: "Answers in the moment",
    detail:
      "Reads your transcript and the cited passages, then writes a concise English answer with the source quoted verbatim — all on your Mac.",
    meta: "Qwen 2.5 7B (4-bit MLX) · ≈ 4 GB",
    approxBytes: 4_000 * 1024 * 1024,
  },
];

export function Setup({
  onDismiss,
  mode = "setup",
}: {
  onDismiss: () => void;
  /** "setup" — first launch. Dismiss is "Continue" and stays disabled
   *  until every row is `done`. The user can't skip past the gate.
   *  "manage" — re-opened from the main app's header to review or
   *  re-trigger downloads. Dismiss is "Close" and always enabled. */
  mode?: "setup" | "manage";
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    ROWS.map((r) => ({
      ...r,
      status: "pending" as RowStatus,
      modelStates: Object.fromEntries(
        r.modelKeys.map((k) => [k, "pending" as const]),
      ),
      bytes: {},
    })),
  );
  const [sidecarReady, setSidecarReady] = useState(false);
  /** Visible boot-time error — set when `sidecar_start` rejects with a
   *  spawn failure (uv missing, helper binary missing, etc.). Surfaced
   *  in a banner so the user can see *why* the sidecar didn't start
   *  instead of just "not reachable" once they hit Download. */
  const [bootError, setBootError] = useState<string | null>(null);
  /** Recent stderr lines from the sidecar process. Whenever the user is
   *  stuck (no events from a row, watchdog fires, boot error), these
   *  are the most useful diagnostic — Python tracebacks, missing-module
   *  errors, etc. all show up here. */
  const [stderrLog, setStderrLog] = useState<string[]>([]);
  const [now, setNow] = useState<number>(Date.now());

  // Tick once a quarter-second so loading rows show real elapsed time.
  useEffect(() => {
    const anyLoading = rows.some((r) => r.status === "loading");
    if (!anyLoading) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [rows]);

  // Boot the sidecar and listen for events.
  //
  // Important: attach the listener BEFORE awaiting startSidecar(). The
  // earlier order produced a race where the sidecar booted and emitted
  // `ready` between startSidecar resolving and onSidecarEvent attaching,
  // leaving us in a permanent `sidecarReady = false` state with download
  // buttons greyed out forever.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let cancelled = false;

    (async () => {
      unlisten = await onSidecarEvent((e) => {
        if (cancelled) return;
        handle(e);
      });
      try {
        await startSidecar();
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn("startSidecar failed:", e);
        if (!cancelled) {
          setBootError(e instanceof Error ? e.message : String(e));
        }
      }
    })();

    return () => {
      cancelled = true;
      unlisten?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Once the sidecar is ready, ask it which models are already cached on
  // disk and mark those rows as `done` so the user isn't prompted to
  // re-download anything they've already got.
  useEffect(() => {
    if (!sidecarReady) return;
    void sendCommand({ type: "check_setup" });
  }, [sidecarReady]);

  function updateRow(componentOrCapability: string, patch: (r: Row) => Row) {
    setRows((rs) =>
      rs.map((r) =>
        r.capability === componentOrCapability ||
        r.modelKeys.includes(componentOrCapability)
          ? patch(r)
          : r,
      ),
    );
  }

  function rollUp(states: Row["modelStates"]): RowStatus {
    const values = Object.values(states);
    if (values.some((s) => s === "error")) return "error";
    if (values.every((s) => s === "done")) return "done";
    if (values.some((s) => s === "loading")) return "loading";
    return "pending";
  }

  function handle(e: SidecarEvent) {
    switch (e.type) {
      case "ready":
        setSidecarReady(true);
        setBootError(null);
        break;
      case "log":
        // Keep a rolling buffer of stderr lines so we can show them when
        // something goes wrong. Bounded so a chatty sidecar doesn't grow
        // memory unboundedly.
        setStderrLog((prev) => [...prev, e.message].slice(-40));
        break;
      case "error":
        // Generic sidecar errors that aren't tied to a model row — fold
        // them into the same diagnostic stream.
        setStderrLog((prev) => [...prev, `error: ${e.message}`].slice(-40));
        break;
      case "setup_check":
        // The sidecar reported which capabilities are already on disk.
        // For each `true` entry, flip its row to `done` (with all
        // sub-models marked done) so the row reads "Ready" and the user
        // doesn't see an unneeded Download button.
        setRows((rs) =>
          rs.map((r) => {
            const cached = !!e.components[r.capability];
            if (!cached || r.status === "loading") return r;
            const ms = Object.fromEntries(
              r.modelKeys.map((k) => [k, "done" as const]),
            );
            return {
              ...r,
              modelStates: ms,
              status: "done",
              startedAt: r.startedAt,
              finishedAt: r.finishedAt ?? Date.now(),
            };
          }),
        );
        break;
      case "model_loading":
        updateRow(e.component, (r) => {
          const ms = { ...r.modelStates, [e.component]: "loading" as const };
          return {
            ...r,
            modelStates: ms,
            status: rollUp(ms),
            startedAt: r.startedAt ?? Date.now(),
            errorMessage: undefined,
          };
        });
        break;
      case "model_progress":
        updateRow(e.component, (r) => ({
          ...r,
          bytes: {
            ...r.bytes,
            [e.component]: {
              current: e.current_bytes,
              total: e.total_bytes,
            },
          },
        }));
        break;
      case "model_loaded":
        updateRow(e.component, (r) => {
          const ms = { ...r.modelStates, [e.component]: "done" as const };
          const status = rollUp(ms);
          return {
            ...r,
            modelStates: ms,
            status,
            finishedAt: status === "done" ? Date.now() : r.finishedAt,
          };
        });
        break;
      case "model_error":
        updateRow(e.component, (r) => {
          const ms = { ...r.modelStates, [e.component]: "error" as const };
          return {
            ...r,
            modelStates: ms,
            status: "error",
            errorMessage: e.error,
            finishedAt: Date.now(),
          };
        });
        break;
      default:
        break;
    }
  }

  async function downloadOne(capability: Capability) {
    // Optimistically flip to loading so the user sees feedback immediately,
    // even if the sidecar hasn't reported `ready` yet.
    setRows((rs) =>
      rs.map((r) =>
        r.capability === capability
          ? {
              ...r,
              status: "loading",
              startedAt: Date.now(),
              finishedAt: undefined,
              errorMessage: undefined,
              modelStates: Object.fromEntries(
                r.modelKeys.map((k) => [k, "pending" as const]),
              ),
              bytes: {},
            }
          : r,
      ),
    );
    // Make sure the sidecar is up. `startSidecar` is idempotent on the
    // Rust side — if a process is already running, it's a no-op.
    try {
      await startSidecar();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("startSidecar from downloadOne failed:", err);
      setBootError(err instanceof Error ? err.message : String(err));
    }
    try {
      await sendCommand({ type: "preload", components: [capability] });
    } catch (err) {
      // sendCommand throws when the sidecar isn't reachable — surface that
      // on the row instead of leaving the spinner running silently.
      const message = err instanceof Error ? err.message : String(err);
      setRows((rs) =>
        rs.map((r) =>
          r.capability === capability
            ? {
                ...r,
                status: "error",
                errorMessage: `Sidecar not reachable: ${message}`,
                finishedAt: Date.now(),
              }
            : r,
        ),
      );
      return;
    }

    // Watchdog: if the row is still in `loading` with no model_loading
    // event 20 seconds after the click, the sidecar is wedged or the
    // warmup is hanging silently. Flip the row to error so the user
    // gets *something* to act on.
    window.setTimeout(() => {
      setRows((rs) =>
        rs.map((r) => {
          if (r.capability !== capability) return r;
          if (r.status !== "loading") return r;
          // If any sub-model has reported even one model_loading event,
          // its modelStates entry will have flipped to "loading" too.
          const sawAnyEvent = Object.values(r.modelStates).some(
            (s) => s !== "pending",
          );
          if (sawAnyEvent) return r;
          return {
            ...r,
            status: "error",
            errorMessage:
              "No response from sidecar after 20 s. Likely the sidecar isn't reachable, or its Python deps aren't installed (run `uv sync --extra ml` from `apps/sidecar`).",
            finishedAt: Date.now(),
          };
        }),
      );
    }, 20_000);
  }

  const allDone = rows.every((r) => r.status === "done");

  return (
    <div
      // `justify-center` + `overflow-y-auto` is a footgun: when content is
      // taller than the viewport, flex centering pushes the top edge above
      // the scroll origin so the page is "scrolled down" by default. Using
      // top-aligned layout with vertical padding instead.
      //
      // We deliberately do NOT put `data-tauri-drag-region` on this outer
      // container. The window-drag handler walks up from the click target
      // to find a drag-region ancestor, and would call `preventDefault()`
      // on every mousedown — killing native text selection across the
      // whole screen. Drag is opt-in only on the title-bar strip and the
      // small brand mark below.
      className="fixed inset-0 z-[90] bg-night text-page flex flex-col items-center px-8 pt-20 pb-12 overflow-y-auto"
    >
      {/* Title-bar strip — the only full-width drag region on this view.
          Lines up with the main app's traffic-light nest. */}
      <div
        className="absolute top-0 inset-x-0 h-9"
        data-tauri-drag-region
      />

      <div className="w-full max-w-[680px]">
        {/* Brand mark — also draggable, since users naturally grab a
            window by its logo. Small enough that losing selection on it
            costs nothing. */}
        <div className="flex items-center gap-3 mb-10" data-tauri-drag-region>
          <Wheel size={26} className="text-flame-ember" />
          <span className="font-display text-[1.3rem] text-page">Sarathi</span>
        </div>

        {/* Boot-error banner — shown when the sidecar can't be spawned
            at all OR when any row hit an error. Always carries the
            raw spawn error and the most recent stderr lines from the
            sidecar (Python tracebacks etc.) so the user has actual
            diagnostic info, not just "not reachable". */}
        {(bootError || rows.some((r) => r.status === "error")) && (
          <div className="mb-8 rounded-lg border border-sindoor/50 bg-sindoor/10 px-4 py-3">
            <div className="font-mono text-[10.5px] uppercase tracking-wider2 text-sindoor mb-1.5">
              Setup is stuck
            </div>
            {bootError && (
              <div className="text-[13px] text-page leading-relaxed">
                {bootError}
              </div>
            )}
            <div className="text-[12px] text-page-dim mt-2 leading-relaxed">
              Check that <code className="font-mono">uv</code> is on your{" "}
              <code className="font-mono">PATH</code>, and that{" "}
              <code className="font-mono">uv sync --extra ml</code> ran
              successfully inside <code className="font-mono">apps/sidecar</code>.
            </div>

            {stderrLog.length > 0 && (
              <details className="mt-3" open>
                <summary className="font-mono text-[10.5px] uppercase tracking-wider2 text-page-ghost cursor-pointer select-none">
                  Sidecar stderr ({stderrLog.length})
                </summary>
                <pre className="font-mono text-[11px] leading-snug text-page-dim mt-2 max-h-[180px] overflow-y-auto whitespace-pre-wrap break-words bg-night-deep/60 rounded px-3 py-2 border border-page-rule">
                  {stderrLog.join("\n")}
                </pre>
              </details>
            )}
          </div>
        )}

        {/* Headline */}
        <h1 className="font-display font-light text-[clamp(2rem,5vw,3.4rem)] leading-[0.96] text-page">
          {mode === "manage" ? (
            <>
              Manage <span className="italicize text-flame-ember">models</span>.
            </>
          ) : allDone ? (
            <>
              Ready to <span className="italicize text-flame-ember">begin</span>.
            </>
          ) : (
            <>
              First, the <span className="italicize text-flame-ember">setup</span>.
            </>
          )}
        </h1>

        <p className="mt-6 text-[14.5px] leading-[1.6] text-page-dim max-w-[58ch]">
          {mode === "manage"
            ? "Review what's installed on your machine. Re-download any capability that's been removed, or close this view to return to the app."
            : allDone
              ? "Everything is on your machine and ready. Nothing leaves your computer from here on."
              : "Sarathi runs entirely on your Mac. Download each piece below to set it up. The files stay on your disk and never leave your computer."}
        </p>

        {/* Capability list */}
        <ol className="mt-10 border-t border-b border-page-rule divide-y divide-page-rule">
          {rows.map((r) => {
            const percent = aggregatePercent(r.bytes, r.approxBytes);
            return (
              <li key={r.capability} className="py-7">
                <div className="grid grid-cols-[0.75rem_1fr_auto] items-start gap-5">
                  <Dot status={r.status} />

                  <div className="min-w-0">
                    <div className="text-[15px] text-page leading-snug">
                      {r.need}
                    </div>
                    <p className="text-[13px] leading-[1.6] text-page-dim mt-2 max-w-[52ch]">
                      {r.detail}
                    </p>
                    <p className="font-mono text-[10.5px] uppercase tracking-wider2 text-page-ghost mt-3">
                      {r.meta}
                    </p>
                    {r.errorMessage && (
                      <p className="text-[12px] text-sindoor mt-2">
                        {r.errorMessage}
                      </p>
                    )}
                  </div>

                  <RowAction
                    row={r}
                    now={now}
                    onDownload={() => void downloadOne(r.capability)}
                  />
                </div>

                {r.status === "loading" && (
                  <ProgressBar row={r} percent={percent} />
                )}
              </li>
            );
          })}
        </ol>

        {/* Footer — single dismiss action.
            In setup mode this is "Continue" and is gated on every row
            being `done`. In manage mode it's "Close" and is always
            enabled (the user has already passed the setup gate, this
            is a review). No more Skip — setup is mandatory. */}
        <div className="mt-10 flex items-center justify-end gap-6">
          {mode === "manage" ? (
            <button
              onClick={onDismiss}
              className="px-6 py-3 text-[13.5px] font-medium tracking-tight rounded-full bg-flame text-night-deep hover:bg-flame-ember transition"
            >
              Close
            </button>
          ) : (
            <button
              onClick={onDismiss}
              disabled={!allDone}
              className={
                "px-6 py-3 text-[13.5px] font-medium tracking-tight rounded-full transition " +
                (allDone
                  ? "bg-flame text-night-deep hover:bg-flame-ember"
                  : "bg-page/10 text-page-ghost cursor-not-allowed")
              }
            >
              Continue
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Dot({ status }: { status: RowStatus }) {
  const color =
    status === "loading"
      ? "bg-flame animate-pulse"
      : status === "done"
        ? "bg-flame-ember"
        : status === "error"
          ? "bg-sindoor"
          : "bg-page/25";
  return <span className={`mt-2 w-2 h-2 rounded-full shrink-0 ${color}`} />;
}

/** Aggregate percent for a row.
 *
 *  The numerator is the cumulative bytes downloaded across every
 *  sub-model. The denominator is the row's *declared* `approxBytes` —
 *  not the observed total from tqdm. This is intentional: tqdm only
 *  knows about files that have already started, so the observed total
 *  grows mid-download as new files register, which would drag percent
 *  backwards. The declared total is fixed up-front per row, so percent
 *  only ever climbs.
 *
 *  Returns null if no progress data has arrived yet (so the bar can
 *  show its indeterminate shimmer instead of a stuck 0%).
 */
function aggregatePercent(
  bytes: Record<string, { current: number; total: number }>,
  approxBytes: number,
): number | null {
  let current = 0;
  let sawAny = false;
  for (const b of Object.values(bytes)) {
    if (b.current > 0 || b.total > 0) sawAny = true;
    current += Math.max(0, b.current);
  }
  if (!sawAny || approxBytes <= 0) return null;
  return Math.min(100, (current / approxBytes) * 100);
}

function ProgressBar({
  row,
  percent,
}: {
  row: Row;
  percent: number | null;
}) {
  // Real numbers in MB. The user sees these tick up — confidence that
  // download is actually happening, beyond the visual fill.
  const downloadedBytes = Object.values(row.bytes).reduce(
    (sum, b) => sum + Math.max(0, b.current),
    0,
  );
  const downloadedMB = downloadedBytes / (1024 * 1024);
  const approxMB = row.approxBytes / (1024 * 1024);
  const fmt = (mb: number) =>
    mb >= 1000 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(0)} MB`;

  return (
    <div className="mt-5 flex items-center gap-5">
      <div className="flex-1 h-3 rounded-full bg-page-rule overflow-hidden relative">
        {percent == null ? (
          <div className="absolute inset-y-0 w-1/3 bg-flame animate-progress-shimmer rounded-full" />
        ) : (
          <div
            className="h-full bg-flame rounded-full transition-[width] duration-200 ease-out"
            // Floor of 1.5% so even at 0.1% there's a visible saffron sliver,
            // confirming the bar is alive rather than empty.
            style={{
              width: `${Math.max(1.5, Math.min(100, percent))}%`,
            }}
          />
        )}
      </div>
      <div className="font-mono text-[11px] tabular-nums text-page-dim whitespace-nowrap">
        {fmt(downloadedMB)} <span className="text-page-ghost">/ ~{fmt(approxMB)}</span>
      </div>
    </div>
  );
}

function RowAction({
  row,
  now,
  onDownload,
}: {
  row: Row;
  now: number;
  onDownload: () => void;
}) {
  if (row.status === "loading") {
    const elapsed = Math.max(
      0,
      Math.floor((now - (row.startedAt ?? now)) / 1000),
    );
    return (
      <span className="font-mono text-[10.5px] uppercase tracking-wider2 text-flame tabular-nums whitespace-nowrap">
        downloading · {elapsed}s
      </span>
    );
  }

  if (row.status === "done") {
    return (
      <span className="font-mono text-[10.5px] uppercase tracking-wider2 text-flame-ember whitespace-nowrap">
        downloaded ✓
      </span>
    );
  }

  // pending or error: show a button. Always enabled — `downloadOne`
  // ensures the sidecar is up before sending the preload command.
  return (
    <button
      onClick={onDownload}
      className={
        "px-4 py-2 text-[12px] tracking-tight rounded-full border whitespace-nowrap transition " +
        (row.status === "error"
          ? "border-sindoor/60 text-sindoor hover:bg-sindoor/10"
          : "border-page/30 text-page hover:bg-page/10")
      }
    >
      {row.status === "error" ? "Retry" : "Download"}
    </button>
  );
}
