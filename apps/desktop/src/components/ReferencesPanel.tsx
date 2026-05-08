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
    <div className="h-full overflow-y-auto px-5 py-6 space-y-4 border-l border-page-rule">
      {cards.length === 0 ? (
        <p className="font-display italicize text-[1.05rem] text-page-ghost leading-snug">
          References appear here when a question is detected or when something
          in the transcript matches your uploaded documents.
        </p>
      ) : (
        cards.map((card) => (
          <div
            key={card.id}
            className="rounded-lg bg-night-rise/60 border border-page-rule p-4"
          >
            <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider2 mb-3">
              <span
                className={
                  card.trigger === "question" ? "text-flame-ember" : "text-flame"
                }
              >
                {card.trigger}
              </span>
              <span className="text-page-ghost">
                {new Date(card.receivedAt).toLocaleTimeString()}
              </span>
            </div>

            <p className="font-mono text-[11px] text-page-ghost mb-3 leading-relaxed">
              query: <span className="text-page">{card.query}</span>
            </p>

            {card.answer && (
              <div className="font-display italicize text-[1.05rem] text-page leading-[1.45] mb-4 whitespace-pre-wrap">
                {card.answer}
              </div>
            )}

            <ol className="space-y-3">
              {card.citations.map((c, i) => (
                <li key={c.chunk_id} className="text-[12px]">
                  <div className="font-mono text-[10px] text-page-ghost mb-1 tracking-wider2 uppercase">
                    [c{i + 1}]{" "}
                    {c.source && (
                      <span>
                        {basename(c.source)}
                        {c.page ? ` · p.${c.page}` : ""}
                      </span>
                    )}
                  </div>
                  <p className="text-page-dim leading-snug">{c.text}</p>
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
