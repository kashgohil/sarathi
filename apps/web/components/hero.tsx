import Link from "next/link";

/**
 * Hero — full viewport, image as the sole subject.
 *
 * Image fills the section as a CSS background (avoids `next/image` quirks
 * with masks/filters). A grain pseudo-element over it adds tooth. A subtle
 * vertical fade lets the headline sit cleanly. Type is bottom-anchored
 * inside the same 12-column grid the rest of the page uses, so it lines
 * up with downstream sections.
 */
export function Hero() {
  return (
    <section className="relative h-[100svh] min-h-[640px] w-full overflow-hidden">
      <div className="hero-image" />
      <div className="hero-fade" />
      <div className="hero-top-fade" />

      <div className="relative z-10 h-full flex flex-col px-6 lg:px-12 pb-14 lg:pb-20">
        <div className="flex-1" />

        <div className="mx-auto w-full max-w-[1320px] grid grid-cols-12 gap-x-6 lg:gap-x-10 stagger">
          <div className="col-span-12 lg:col-span-8 xl:col-span-7">
            <h1 className="font-display font-light text-page leading-[0.92] text-[clamp(3rem,9vw,7.5rem)]">
              Every conversation
              <br />
              <span className="italicize text-flame-ember">deserves</span> a
              <br />
              charioteer.
            </h1>

            <p className="mt-8 max-w-[44ch] text-[16px] leading-[1.6] text-page-dim">
              Sarathi is a desktop assistant that listens to your meetings
              and calls, transcribes them on your Mac, and quietly hands you
              the right page from your own documents — in the moment you
              need it. Multilingual, cited, fully on-device.
            </p>

            <div className="mt-9 flex flex-wrap items-center gap-x-6 gap-y-3">
              <Link
                href="#download"
                className="inline-flex items-center gap-3 bg-flame text-night-deep px-6 py-3.5 text-[13.5px] font-medium tracking-tight rounded-full hover:bg-flame-ember transition"
              >
                Download for Mac
                <span className="font-mono text-[10px] opacity-65">
                  M-series · 13+
                </span>
              </Link>
              <a
                href="#how"
                className="text-[13px] tracking-tight text-page-dim hover:text-page transition"
              >
                See how it works ↓
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
