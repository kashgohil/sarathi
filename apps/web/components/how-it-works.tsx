/**
 * How it works — three numbered movements aligned in a clean 12-column
 * grid. Same column anchors as the rest of the page, no asymmetric
 * indents that could read as misalignment.
 */

const steps = [
  {
    n: "I",
    title: "Listen",
    body:
      "Mic or system audio, on-device. A live transcript builds as people speak — speaker-aware, with automatic switching across languages mid-sentence.",
    detail: "whisper-large-v3-turbo · silero VAD · pyannote",
  },
  {
    n: "II",
    title: "Find",
    body:
      "Your PDFs, scans and notes are read with OCR, normalised, and indexed with multilingual hybrid embeddings. The right page is one query away — even when the question is asked in a different language than the source.",
    detail: "pymupdf · PaddleOCR · BGE-M3 · LanceDB",
  },
  {
    n: "III",
    title: "Cite",
    body:
      "Answers come back in English. Citations stay verbatim in the original — the page they came from, in the language it was written in — so you can verify the source the moment it's quoted.",
    detail: "Qwen 2.5 · MLX · per-citation page anchors",
  },
];

export function HowItWorks() {
  return (
    <section
      id="how"
      className="relative px-6 lg:px-12 py-28 lg:py-40 border-t border-page-rule"
    >
      <div className="mx-auto w-full max-w-[1320px]">
        {/* Section header lined up to the same 12-col grid as the rows. */}
        <div className="grid grid-cols-12 gap-x-6 lg:gap-x-10 mb-20 lg:mb-28">
          <p className="col-span-12 md:col-span-3 font-mono text-[10.5px] uppercase tracking-[0.22em] text-page-ghost mb-3 md:mb-0 md:pt-3">
            How it works
          </p>
          <h2 className="col-span-12 md:col-span-9 font-display font-light text-[clamp(2.5rem,6vw,5rem)] leading-[0.95] text-page">
            Three movements,
            <br />
            <span className="italicize text-flame-ember">in sequence</span>.
          </h2>
        </div>

        <ol className="divide-y divide-page-rule border-t border-b border-page-rule">
          {steps.map((s) => (
            <li
              key={s.n}
              className="grid grid-cols-12 gap-x-6 lg:gap-x-10 py-12 lg:py-16 items-start"
            >
              <div className="col-span-12 md:col-span-3 flex items-baseline gap-4">
                <span className="font-display italicize text-[2.4rem] leading-none text-sindoor tabular-nums">
                  {s.n}
                </span>
                <span className="font-display italicize text-[2rem] leading-none text-page">
                  {s.title}
                </span>
              </div>

              <div className="col-span-12 md:col-span-9 mt-5 md:mt-2">
                <p className="text-[16.5px] leading-[1.62] text-page-dim max-w-[60ch]">
                  {s.body}
                </p>
                <p className="mt-5 font-mono text-[10.5px] uppercase tracking-[0.22em] text-page-ghost">
                  {s.detail}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
