import { openScreenRecordingSettings } from "../lib/sidecar";

export function PermissionBanner({ message }: { message: string }) {
  return (
    <div className="px-5 py-2.5 bg-flame/10 border-b border-flame/30 text-flame-ember text-[12px] tracking-tight flex items-center justify-between">
      <span>
        <strong className="font-medium text-page">
          Screen Recording permission needed
        </strong>
        {message ? <span className="text-page-dim"> — {message}</span> : null}
      </span>
      <button
        onClick={() => void openScreenRecordingSettings()}
        className="px-3 py-1 text-[11px] tracking-tight rounded-full border border-flame/50 text-page hover:bg-flame/20 transition"
      >
        Open System Settings
      </button>
    </div>
  );
}
