import Link from "next/link";
import { Wheel } from "./wheel";

/**
 * Header overlays the hero image at the top. Sticky, transparent, no
 * background fill — the image carries the visual weight, the type is the
 * only thing on top.
 */
export function Header() {
  return (
    <header className="absolute top-0 inset-x-0 z-30 px-6 lg:px-12 pt-7">
      <div className="mx-auto max-w-[1320px] flex items-center justify-between">
        <Link href="/" className="flex items-center gap-3 text-page">
          <Wheel size={26} className="text-flame-ember" />
          <span className="font-display text-[1.4rem]">Sarathi</span>
        </Link>

        <nav className="hidden md:flex items-center gap-8 text-[12.5px] tracking-tight text-page-dim">
          <a href="#verse" className="hover:text-page transition">
            Verse
          </a>
          <a href="#how" className="hover:text-page transition">
            How it works
          </a>
          <a href="#privacy" className="hover:text-page transition">
            Privacy
          </a>
          <a href="#specs" className="hover:text-page transition">
            Specs
          </a>
        </nav>

        <Link
          href="#download"
          className="text-[12.5px] tracking-tight text-flame-ember hover:text-flame transition"
        >
          Download for Mac →
        </Link>
      </div>
    </header>
  );
}
