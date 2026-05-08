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
        className="px-3 py-1.5 text-[11.5px] tracking-tight rounded-full border border-page-rule text-page-dim hover:text-page hover:border-page/40 transition"
      >
        Add document
      </button>
      <button
        onClick={pickDir}
        className="px-3 py-1.5 text-[11.5px] tracking-tight rounded-full border border-page-rule text-page-dim hover:text-page hover:border-page/40 transition"
      >
        Add folder
      </button>
    </div>
  );
}
