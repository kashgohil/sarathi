import { useEffect, useRef } from "react";

export type Utterance = {
  id: string;
  text: string;
  lang: string | null;
  speaker_id: string | null;
  start_s: number;
  end_s: number;
};

// Two-speaker palette built from the brand tokens. Single speaker = the
// primary parchment, second speaker = saffron. We deliberately avoid a
// rainbow per-speaker scheme — most v0 sessions are two-person.
const SPEAKER_COLORS = [
  "text-page",
  "text-flame-ember",
  "text-page",
  "text-flame-ember",
];

function speakerClass(id: string | null): string {
  if (!id) return "text-page";
  const m = id.match(/(\d+)/);
  const idx = m ? parseInt(m[1], 10) : id.charCodeAt(0);
  return SPEAKER_COLORS[idx % SPEAKER_COLORS.length];
}

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
      className="h-full overflow-y-auto px-8 py-7 space-y-3.5 text-[15px] leading-[1.55]"
    >
      {utterances.length === 0 ? (
        <p className="text-page-ghost font-display italicize text-[1.15rem]">
          Press <span className="text-flame-ember not-italic font-sans text-[13px] tracking-tight">Record</span>{" "}
          to begin. Transcripts appear here as you speak.
        </p>
      ) : (
        utterances.map((u) => (
          <div key={u.id} className="flex gap-4">
            <span className="font-mono text-[10.5px] text-page-ghost tabular-nums shrink-0 w-12 text-right pt-1">
              {formatTime(u.start_s)}
            </span>
            <p className={speakerClass(u.speaker_id)}>
              {u.speaker_id && (
                <span className="mr-2 font-mono text-[9.5px] uppercase tracking-wider2 text-page-ghost">
                  {u.speaker_id}
                </span>
              )}
              {u.text}
              {u.lang && (
                <span className="ml-2 font-mono text-[9.5px] uppercase tracking-wider2 text-page-ghost">
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
