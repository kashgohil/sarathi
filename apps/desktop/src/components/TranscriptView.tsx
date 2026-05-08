import { useEffect, useRef } from "react";

export type Utterance = {
  id: string;
  text: string;
  lang: string | null;
  start_s: number;
  end_s: number;
};

export function TranscriptView({ utterances }: { utterances: Utterance[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [utterances.length]);

  return (
    <div
      ref={ref}
      className="h-full overflow-y-auto p-6 space-y-3 text-[15px] leading-relaxed"
    >
      {utterances.length === 0 ? (
        <p className="text-neutral-500 italic">
          Press the record button to start a session. Transcripts appear here as
          you speak.
        </p>
      ) : (
        utterances.map((u) => (
          <div key={u.id} className="flex gap-3">
            <span className="text-neutral-600 tabular-nums shrink-0 w-12 text-right pt-0.5 text-xs">
              {formatTime(u.start_s)}
            </span>
            <p
              className={
                u.lang === "gu"
                  ? "text-neutral-100"
                  : "text-neutral-200"
              }
            >
              {u.text}
              {u.lang && (
                <span className="ml-2 text-[10px] uppercase tracking-wider text-neutral-500">
                  {u.lang}
                </span>
              )}
            </p>
          </div>
        ))
      )}
    </div>
  );
}

function formatTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}
