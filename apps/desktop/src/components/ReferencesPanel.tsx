import type { Citation } from "../lib/sidecar";

export type ReferenceCard = {
  id: string;
  trigger: "question" | "proactive";
  query: string;
  citations: Citation[];
  answer?: string;
  receivedAt: number;
};

export function ReferencesPanel({ cards }: { cards: ReferenceCard[] }) {
  return (
    <div className="h-full overflow-y-auto p-4 space-y-4 border-l border-neutral-800">
      {cards.length === 0 ? (
        <p className="text-neutral-500 text-sm italic">
          References will appear here when a question is detected or when
          something in the transcript matches your uploaded documents.
        </p>
      ) : (
        cards.map((card) => (
          <div
            key={card.id}
            className="rounded-lg bg-neutral-900 border border-neutral-800 p-3"
          >
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider mb-2">
              <span
                className={
                  card.trigger === "question"
                    ? "text-amber-400"
                    : "text-emerald-400"
                }
              >
                {card.trigger}
              </span>
              <span className="text-neutral-500">
                {new Date(card.receivedAt).toLocaleTimeString()}
              </span>
            </div>

            <p className="text-xs text-neutral-400 mb-2">
              query: <span className="text-neutral-200">{card.query}</span>
            </p>

            {card.answer && (
              <div className="text-sm text-neutral-100 mb-3 whitespace-pre-wrap">
                {card.answer}
              </div>
            )}

            <ol className="space-y-2">
              {card.citations.map((c, i) => (
                <li key={c.chunk_id} className="text-xs">
                  <div className="text-neutral-500 mb-1">
                    [c{i + 1}]{" "}
                    {c.source && (
                      <span className="text-neutral-600">
                        {basename(c.source)}
                        {c.page ? ` p.${c.page}` : ""}
                      </span>
                    )}
                  </div>
                  <p
                    className={
                      c.lang === "gu"
                        ? "text-neutral-100 leading-snug"
                        : "text-neutral-200 leading-snug"
                    }
                  >
                    {c.text}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        ))
      )}
    </div>
  );
}

function basename(p: string): string {
  return p.split("/").pop() || p;
}
