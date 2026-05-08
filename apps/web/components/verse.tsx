/**
 * The verse — Bhagavad Gita 1.21. Arjuna asks Krishna, his sarathi, to
 * pause the chariot between the two armies. The same instinct, three
 * thousand years later, in any conversation: pause, see what you're
 * actually facing, then move. No imagery here — the verse is the visual.
 */

export function Verse() {
  return (
    <section
      id="verse"
      className="relative px-6 lg:px-12 py-32 lg:py-44 border-t border-page-rule"
    >
      <div className="mx-auto w-full max-w-[1320px] grid grid-cols-12 gap-x-6 lg:gap-x-10">
        <p className="col-span-12 md:col-span-3 font-mono text-[10.5px] uppercase tracking-[0.22em] text-page-ghost mb-6 md:mb-0 md:pt-3">
          Bhagavadgītā · 1.21
        </p>

        <div className="col-span-12 md:col-span-9">
          <p
            className="font-devanagari text-flame-ember text-[clamp(1.6rem,2.8vw,2.4rem)] leading-[1.4]"
            lang="sa"
          >
            सेनयोरुभयोर्मध्ये
            <br />
            रथं स्थापय मेऽच्युत
          </p>

          <p className="mt-7 font-display italicize font-light text-page text-[clamp(1.4rem,2.4vw,2rem)] leading-[1.32] max-w-[34ch]">
            Place my chariot, O Achyuta,
            <br />
            between the two armies.
          </p>

          <div className="mt-12 max-w-[58ch] text-[15.5px] leading-[1.7] text-page-dim">
            <p>
              Three thousand years later, the conversations still need a
              charioteer. The voices are different — sales calls, clinic
              intakes, parent-teacher meetings, hiring loops — but the wish
              is the same:{" "}
              <span className="marker text-page">
                pause the noise long enough to read what's already written
              </span>
              , then move with clearer eyes.
            </p>
            <p className="mt-5 text-page-ghost">
              Sarathi is the modern sarathi. It listens, finds the page,
              cites the source. Nothing more. Nothing leaves the machine.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
