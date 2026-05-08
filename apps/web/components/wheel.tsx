/**
 * Chariot wheel — brand mark.
 *
 * The geometry lives in `/public/wheel.svg` so the same asset can serve as:
 *   - the browser tab icon (also linked at `app/icon.svg`)
 *   - an `<img>` source on any page or in the desktop app
 *   - this component, which uses CSS mask-image so the colour can be
 *     overridden via `currentColor` (i.e. parent `text-*` classes).
 *
 * The mask trick: we paint a solid `currentColor` background and clip it
 * to the SVG's alpha mask. Result: the wheel renders in whatever colour
 * the parent's text colour is. That's why `<Wheel className="text-flame" />`
 * works without us shipping multiple SVG variants.
 */

const SRC = "/wheel.svg";

export function Wheel({
  size = 22,
  className = "",
  title,
}: {
  size?: number;
  className?: string;
  /** Optional accessible label. Omit for purely decorative usage. */
  title?: string;
}) {
  return (
    <span
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      className={className}
      style={{
        display: "inline-block",
        width: size,
        height: size,
        backgroundColor: "currentColor",
        WebkitMaskImage: `url(${SRC})`,
        maskImage: `url(${SRC})`,
        WebkitMaskRepeat: "no-repeat",
        maskRepeat: "no-repeat",
        WebkitMaskSize: "contain",
        maskSize: "contain",
        WebkitMaskPosition: "center",
        maskPosition: "center",
      }}
    />
  );
}
