/**
 * Chariot wheel — brand mark, mirrored from the marketing site.
 *
 * Geometry lives in `src/assets/wheel.svg`. We let Vite resolve the URL
 * (so it gets fingerprinted at build time), then use CSS mask-image so
 * the parent's `currentColor` decides what colour the wheel renders in.
 */

import wheelUrl from "../assets/wheel.svg";

export function Wheel({
  size = 22,
  className = "",
  title,
}: {
  size?: number;
  className?: string;
  /** Optional accessible label. Omit for decorative usage. */
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
        WebkitMaskImage: `url(${wheelUrl})`,
        maskImage: `url(${wheelUrl})`,
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
