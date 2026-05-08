/**
 * Privacy — same grid as everything else. Clean column anchors, no glow,
 * no decorative halo. Type does the work.
 */

const lines = [
  "no servers · no telemetry · no analytics",
  "no cloud transcription · no cloud embedding · no cloud LLM",
  "your audio · your documents · your machine",
];

export function PrivacyStripe() {
  return (
    <section
      id="privacy"
      className="relative px-6 lg:px-12 py-32 lg:py-44 border-t border-page-rule"
    >
      <div className="mx-auto w-full max-w-[1320px] grid grid-cols-12 gap-x-6 lg:gap-x-10">
        <p className="col-span-12 md:col-span-3 font-mono text-[10.5px] uppercase tracking-[0.22em] text-page-ghost mb-6 md:mb-0 md:pt-3">
          Privacy
        </p>

        <div className="col-span-12 md:col-span-9">
          <h2 className="font-display font-light text-[clamp(2.5rem,6vw,5rem)] leading-[0.95] text-page">
            Built so the
            <br />
            <span className="italicize text-flame-ember">recording</span>{" "}
            stops mattering
            <br />
            at end-of-meeting.
          </h2>

          <ul className="mt-12 space-y-3 font-mono text-[12.5px] tracking-tight text-page-dim">
            {lines.map((l) => (
              <li key={l} className="flex items-start gap-3">
                <span className="text-sindoor select-none mt-[2px]">→</span>
                <span>{l}</span>
              </li>
            ))}
          </ul>

          <div className="mt-14 grid grid-cols-12 gap-x-6 lg:gap-x-10 border-t border-page-rule pt-10">
            <p className="col-span-12 md:col-span-5 font-display italicize font-light text-page text-[1.6rem] leading-[1.18]">
              Retained 15 days,
              <br />
              then forgotten.
            </p>
            <p className="col-span-12 md:col-span-7 mt-5 md:mt-1 text-[14.5px] leading-[1.65] text-page-dim">
              Transcripts auto-vacuum on a rolling fortnight — long enough
              to search backwards through a week of work, short enough that
              nothing accidentally lives forever. Indexed documents persist;
              conversations don't.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
