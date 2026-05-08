import { open } from "@tauri-apps/plugin-dialog";
import { sendCommand } from "../lib/sidecar";

export function DocUpload({ onIngestRequested }: { onIngestRequested?: (path: string) => void }) {
  async function pick() {
    const selected = await open({
      multiple: false,
      directory: false,
      filters: [
        {
          name: "Documents",
          extensions: ["pdf", "txt", "md", "png", "jpg", "jpeg"],
        },
      ],
    });
    if (!selected) return;
    const path = Array.isArray(selected) ? selected[0] : selected;
    onIngestRequested?.(path);
    await sendCommand({ type: "ingest", path });
  }

  async function pickDir() {
    const selected = await open({ multiple: false, directory: true });
    if (!selected) return;
    const path = Array.isArray(selected) ? selected[0] : selected;
    onIngestRequested?.(path);
    await sendCommand({ type: "ingest", path });
  }

  return (
    <div className="flex gap-2">
      <button
        onClick={pick}
        className="px-3 py-1.5 text-xs rounded border border-neutral-700 hover:bg-neutral-800"
      >
        Add document
      </button>
      <button
        onClick={pickDir}
        className="px-3 py-1.5 text-xs rounded border border-neutral-700 hover:bg-neutral-800"
      >
        Add folder
      </button>
    </div>
  );
}
