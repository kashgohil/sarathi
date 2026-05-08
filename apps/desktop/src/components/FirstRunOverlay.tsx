import { useEffect, useMemo, useState } from "react";
import type { SidecarEvent } from "../lib/sidecar";

/**
 * First-run / model-load overlay.
 *
 * Watches `model_loading` / `model_loaded` events from the sidecar and
 * renders a calm status board. Auto-hides when:
 *   - the user clicks "continue", OR
 *   - there has been no activity for `IDLE_DISMISS_MS` AND every
 *     loading component has reported `loaded`.
 *
 * Aesthetic: status-board / boot-log. Monospace details, hairline rules,
 * sindoor accent for "loading", deep-amber for warnings.
 */

type Status = "loading" | "loaded" | "error";

type ComponentRow = {
  component: string;
  label: string;
  approx_mb: number | null;
  status: Status;
  startedAt: number;
  finishedAt?: number;
  error?: string;
};

const IDLE_DISMISS_MS = 1500;

export function FirstRunOverlay({
  events,
}: {
  /** A continuous stream of sidecar events. We extract model_* events. */
  events: SidecarEvent[];
}) {
  const [rows, setRows] = useState<Record<string, ComponentRow>>({});
  const [dismissed, setDismissed] = useState(false);
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);

  // Translate the event log into a rows-by-component map. We re-derive on
  // every change rather than tracking a separate state machine.
  useEffect(() => {
    const next: Record<string, ComponentRow> = {};
    let last: number | null = null;
    for (const e of events) {
      if (
        e.type !== "model_loading" &&
        e.type !== "model_loaded" &&
        e.type !== "model_error"
      ) {
        continue;
      }
      last = Date.now();
      const cur = next[e.component] ?? {
        component: e.component,
        label: e.label,
        approx_mb: null as number | null,
        status: "loading" as Status,
        startedAt: Date.now(),
      };
      if (e.type === "model_loading") {
        cur.status = "loading";
        cur.label = e.label;
        cur.approx_mb = e.approx_mb;
        cur.startedAt = Date.now();
        cur.finishedAt = undefined;
        cur.error = undefined;
      } else if (e.type === "model_loaded") {
        cur.status = "loaded";
        cur.finishedAt = Date.now();
      } else if (e.type === "model_error") {
        cur.status = "error";
        cur.finishedAt = Date.now();
        cur.error = e.error;
      }
      next[e.component] = cur;
    }
    setRows(next);
    setLastEventAt(last);
  }, [events]);

  const list = useMemo(() => Object.values(rows), [rows]);
  const anyActive = list.some((r) => r.status === "loading");
  const hasAny = list.length > 0;

  // Auto-dismiss after a stretch of quiet, all-loaded.
  useEffect(() => {
    if (!hasAny || anyActive || lastEventAt == null) return;
    const t = setTimeout(() => setDismissed(true), IDLE_DISMISS_MS);
    return () => clearTimeout(t);
  }, [hasAny, anyActive, lastEventAt]);

  // Re-show the overlay if a brand-new loading event arrives after dismiss.
  useEffect(() => {
    if (anyActive) setDismissed(false);
  }, [anyActive]);

  if (!hasAny || dismissed) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-night-deep/85 backdrop-blur-md">
      <div className="w-[min(640px,92vw)] rounded-xl border border-page-rule bg-night-rise">
        {/* Header strip */}
        <div className="px-5 py-3.5 border-b border-page-rule flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span
              className={
                "w-1.5 h-1.5 rounded-full " +
                (anyActive ? "bg-flame animate-pulse" : "bg-flame-ember")
              }
            />
            <span className="font-mono text-[10.5px] uppercase tracking-wider2 text-page-dim">
              {anyActive ? "Loading models" : "Models ready"}
            </span>
          </div>
          <span className="font-mono text-[10.5px] text-page-ghost">
            {summary(list)}
          </span>
        </div>

        {/* Title */}
        <div className="px-5 pt-5 pb-2">
          <h2 className="font-display italicize text-[1.4rem] text-page leading-tight">
            {anyActive ? "Preparing the local pipeline." : "Pipeline ready."}
          </h2>
          <p className="text-[12.5px] text-page-ghost mt-2 leading-relaxed">
            Models load on demand. The first launch downloads weights to your
            machine. Subsequent launches reuse them.
          </p>
        </div>

        {/* Rows */}
        <ol className="px-5 pb-2 mt-2">
          {list.map((r) => (
            <Row key={r.component} row={r} now={lastEventAt ?? Date.now()} />
          ))}
        </ol>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-page-rule flex items-center justify-between">
          <span className="font-mono text-[10.5px] text-page-ghost">
            on-device · forever
          </span>
          <button
            onClick={() => setDismissed(true)}
            disabled={anyActive}
            className={
              "text-[12px] tracking-tight px-4 py-1.5 rounded-full border transition " +
              (anyActive
                ? "border-page-rule text-page-ghost cursor-not-allowed"
                : "border-page/30 text-page hover:bg-page/10")
            }
          >
            {anyActive ? "Working…" : "Continue"}
          </button>
        </div>
      </div>
    </div>
  );
}

function summary(rows: ComponentRow[]): string {
  if (rows.length === 0) return "";
  const loaded = rows.filter((r) => r.status === "loaded").length;
  return `${loaded}/${rows.length}`;
}

function Row({ row, now }: { row: ComponentRow; now: number }) {
  const elapsed =
    row.status === "loading"
      ? Math.max(0, Math.floor((now - row.startedAt) / 1000))
      : row.finishedAt
      ? Math.max(0, Math.floor((row.finishedAt - row.startedAt) / 1000))
      : 0;

  const dotColor =
    row.status === "loading"
      ? "bg-flame animate-pulse"
      : row.status === "loaded"
      ? "bg-flame-ember"
      : "bg-sindoor";

  const dimensionsLabel = row.approx_mb
    ? row.approx_mb >= 1000
      ? `≈ ${(row.approx_mb / 1000).toFixed(1)} GB`
      : `≈ ${row.approx_mb} MB`
    : "—";

  return (
    <li className="grid grid-cols-[1.25rem_1fr_auto_auto] items-center gap-3 py-2.5 border-b border-page-rule last:border-b-0">
      <span className={`w-2 h-2 rounded-full ${dotColor}`} />

      <div className="min-w-0">
        <div className="text-[13px] text-page truncate">{row.label}</div>
        {row.error ? (
          <div className="text-[11px] text-sindoor truncate mt-0.5">
            {row.error}
          </div>
        ) : (
          <div className="font-mono text-[10.5px] text-page-ghost truncate">
            {row.component}
          </div>
        )}
      </div>

      <span className="font-mono text-[10.5px] text-page-ghost tabular-nums">
        {dimensionsLabel}
      </span>
      <span
        className={
          "font-mono text-[10.5px] tabular-nums " +
          (row.status === "loading" ? "text-flame" : "text-page-ghost")
        }
      >
        {row.status === "loading"
          ? `${elapsed}s`
          : row.status === "loaded"
          ? `${elapsed}s ✓`
          : "error"}
      </span>
    </li>
  );
}
