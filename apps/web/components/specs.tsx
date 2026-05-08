/**
 * Specs — colophon table aligned to the same 12-column grid as the rest of
 * the page. Every row is a real fact, no marketing filler.
 */

import type { ReactNode } from "react";

const rows: Array<[string, ReactNode]> = [
  ["Platform", "macOS 13 Ventura or later · Apple Silicon"],
  ["Memory", "16 GB minimum · 24 GB recommended"],
  ["Disk", "≈ 7.5 GB models · ≈ 3 GB application"],
  ["Audio", "Microphone · System (Zoom, Meet, Teams) · Both, mixed"],
  ["Languages", "Multiple, auto-detected per utterance"],
  ["Answers", "English, with citations verbatim in source language"],
  ["Network", "First-launch model download. Offline thereafter."],
  ["Telemetry", "None."],
];

export function Specs() {
  return (
    <section
      id="specs"
      className="relative px-6 lg:px-12 py-28 lg:py-40 border-t border-page-rule"
    >
      <div className="mx-auto w-full max-w-[1320px] grid grid-cols-12 gap-x-6 lg:gap-x-10">
        <div className="col-span-12 md:col-span-3 mb-10 md:mb-0">
          <p className="font-mono text-[10.5px] uppercase tracking-[0.22em] text-page-ghost mb-3">
            Specs
          </p>
          <h2 className="font-display italicize font-light text-[2.6rem] leading-[0.95] text-page">
            What's
            <br />
            inside.
          </h2>
        </div>

        <dl className="col-span-12 md:col-span-9 divide-y divide-page-rule border-t border-b border-page-rule">
          {rows.map(([k, v]) => (
            <div
              key={k}
              className="grid grid-cols-12 gap-x-4 py-4 items-baseline"
            >
              <dt className="col-span-12 sm:col-span-4 font-mono text-[10.5px] uppercase tracking-[0.22em] text-page-ghost">
                {k}
              </dt>
              <dd className="col-span-12 sm:col-span-8 mt-1 sm:mt-0 text-[15px] tracking-tight text-page">
                {v}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
