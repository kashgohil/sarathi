import { openScreenRecordingSettings } from "../lib/sidecar";

export function PermissionBanner({ message }: { message: string }) {
  return (
    <div className="px-4 py-2 bg-amber-500/10 border-b border-amber-500/30 text-amber-200 text-xs flex items-center justify-between">
      <span>
        <strong className="font-medium">Screen Recording permission needed</strong>
        {message ? <> — {message}</> : null}
      </span>
      <button
        onClick={() => void openScreenRecordingSettings()}
        className="px-2 py-1 text-[11px] rounded border border-amber-400/50 hover:bg-amber-500/20"
      >
        Open System Settings
      </button>
    </div>
  );
}
