/**
 * Footer — final reprise on the same 12-col grid. No glow, no halo, no
 * gradient. The CTA is a clean filled pill, the imprint line lists the
 * type families and ships.
 */

import { Wheel } from "./wheel";

export function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer
      id="download"
      className="relative px-6 lg:px-12 pt-28 pb-10 border-t border-page-rule"
    >
      <div className="mx-auto w-full max-w-[1320px]">
        <div className="grid grid-cols-12 gap-x-6 lg:gap-x-10 items-end">
          <div className="col-span-12 md:col-span-7">
            <p className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-page-ghost mb-5">
              Take it home
            </p>
            <h2 className="font-display font-light text-[clamp(2.5rem,6vw,5rem)] leading-[0.95] text-page">
              Place your
              <br />
              <span className="italicize text-flame-ember">chariot</span>
              <br />
              between the armies.
            </h2>
          </div>

          <div className="col-span-12 md:col-span-5 mt-10 md:mt-0">
            <a
              href="#"
              className="group block rounded-2xl border border-flame/40 hover:border-flame transition px-7 py-6"
            >
              <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-flame-ember/80 group-hover:text-flame-ember">
                For macOS · Apple Silicon
              </span>
              <div className="font-display italicize font-light text-page text-[1.95rem] leading-tight mt-1">
                Download Sarathi
              </div>
              <div className="font-mono text-[10.5px] text-page-ghost mt-1">
                v0.0.1 · ~ 3 GB · models on first launch
              </div>
            </a>
          </div>
        </div>

        {/* Imprint */}
        <div className="mt-24 pt-8 border-t border-page-rule grid grid-cols-12 gap-x-6 lg:gap-x-10 text-[12px] tracking-tight text-page-ghost font-mono">
          <p className="col-span-12 md:col-span-7">
            Set in <span className="text-page">Cormorant Garamond</span>,{" "}
            <span className="text-page">Plus Jakarta Sans</span>, and{" "}
            <span className="text-page">JetBrains Mono</span>.
          </p>
          <p className="col-span-6 md:col-span-3 mt-3 md:mt-0 inline-flex items-center gap-2">
            <Wheel size={16} className="text-flame-ember" />
            <span>Sarathi · {year}</span>
          </p>
          <p className="col-span-6 md:col-span-2 mt-3 md:mt-0 md:text-right">
            on-device · forever
          </p>
        </div>

        <p className="mt-6 text-[10.5px] font-mono text-page-faint max-w-[60ch]">
          Hero imagery licensed from artist for use on this page.
        </p>
      </div>
    </footer>
  );
}
