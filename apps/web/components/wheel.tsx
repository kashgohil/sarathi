/**
 * Chariot wheel — the brand mark.
 *
 * Real chariot wheels (the kind on the painting we use in the hero) have:
 *   - a heavy outer iron tire,
 *   - a felloe band inside it,
 *   - 12 spokes (war-chariot count, also dharma-chakra adjacent),
 *   - a substantial banded hub,
 *   - a visible central axle pin.
 *
 * The 8-spoke wagon-wheel emoji-shape reads as generic; this version
 * carries enough structural detail to feel built rather than drawn,
 * while staying crisp at 16-26px. Stroke-only line work, single color
 * via `currentColor`. One small filled axle-pin in the very center is
 * the only non-stroked element.
 */

const SPOKES = 12;

export function Wheel({
  size = 22,
  className = "",
  spinning = false,
}: {
  size?: number;
  className?: string;
  /** Add the slow rotation. */
  spinning?: boolean;
}) {
  // Geometry, in a 64-unit viewBox centered at (32, 32).
  const C = 32;
  const R_TIRE = 30;          // outer iron tire
  const R_FELLOE = 26.5;      // inner rim line — gap between tire and felloe
  const R_HUB_OUT = 9;        // hub outer band
  const R_HUB_IN = 6.5;       // hub inner band
  const R_HUB_DISC = 3.6;     // filled hub disc
  const R_PIN = 1.1;          // central axle pin (filled)

  const spokeInner = R_HUB_OUT - 0.2;
  const spokeOuter = R_FELLOE - 0.4;

  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      className={`${className} ${spinning ? "animate-wheel" : ""}`}
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {/* Outer iron tire — the heavy band. */}
      <circle cx={C} cy={C} r={R_TIRE} strokeWidth="2" />

      {/* Felloe — inner rim, thinner. The visible gap between this and
          the tire suggests the layered construction of a real wheel. */}
      <circle cx={C} cy={C} r={R_FELLOE} strokeWidth="0.9" />

      {/* Spokes — 12, drawn from hub band to felloe band so they don't
          poke through either ring. */}
      {Array.from({ length: SPOKES }).map((_, i) => {
        const a = (i * Math.PI * 2) / SPOKES;
        const x1 = C + Math.cos(a) * spokeInner;
        const y1 = C + Math.sin(a) * spokeInner;
        const x2 = C + Math.cos(a) * spokeOuter;
        const y2 = C + Math.sin(a) * spokeOuter;
        return (
          <line
            key={i}
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            strokeWidth="0.9"
          />
        );
      })}

      {/* Hub — outer band */}
      <circle cx={C} cy={C} r={R_HUB_OUT} strokeWidth="1.4" />
      {/* Hub — inner band, slightly thinner. The double ring is what
          gives the hub presence at small sizes. */}
      <circle cx={C} cy={C} r={R_HUB_IN} strokeWidth="0.7" />

      {/* Hub disc — filled, so the spoke roots are anchored visually. */}
      <circle cx={C} cy={C} r={R_HUB_DISC} fill="currentColor" stroke="none" />

      {/* Central axle pin — a tiny "negative space" dot punched through
          the hub disc, suggesting the iron pin at the wheel's center. */}
      <circle
        cx={C}
        cy={C}
        r={R_PIN}
        fill="var(--night-deep, #060A1B)"
        stroke="none"
      />
    </svg>
  );
}
