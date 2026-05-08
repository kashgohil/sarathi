import { useEffect, useState } from "react";
import krishnaArjuna from "../assets/krishna-arjuna.jpg";

/**
 * Launch splash.
 *
 * Mirrors the marketing-site hero exactly:
 *   - same Krishna-Arjuna painting, full bleed
 *   - same scrims (left + bottom + top fade)
 *   - same lower-left composition: "Every conversation deserves a charioteer."
 *     in display serif with a saffron `deserves` accent, plus the same
 *     paragraph copy beneath it
 *
 * Sequence:
 *   t=0      image fades + scales in (900ms)
 *   t=1.0s   headline + body slide up
 *   t=3.4s   whole splash starts fading out + scaling
 *   t=4.0s   splash unmounts, app visible
 *
 * Click or Esc/Enter skips. Hold is longer than before because there's
 * more copy to read; users who want to dismiss will skip.
 */

const SHOW_TEXT_AT = 1000;
const START_LEAVE_AT = 3400;
const UNMOUNT_AT = 4000;

export function Splash({ onDone }: { onDone: () => void }) {
  const [showText, setShowText] = useState(false);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const timers = [
      window.setTimeout(() => setShowText(true), SHOW_TEXT_AT),
      window.setTimeout(() => setLeaving(true), START_LEAVE_AT),
      window.setTimeout(onDone, UNMOUNT_AT),
    ];

    function skip() {
      timers.forEach(clearTimeout);
      setShowText(true);
      setLeaving(true);
      window.setTimeout(onDone, 350);
    }

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" || e.key === "Enter") skip();
    }
    window.addEventListener("keydown", onKey);

    return () => {
      timers.forEach(clearTimeout);
      window.removeEventListener("keydown", onKey);
    };
  }, [onDone]);

  return (
    <div
      className={
        "fixed inset-0 z-[100] bg-night-deep cursor-pointer overflow-hidden " +
        (leaving ? "animate-splash-out pointer-events-none" : "")
      }
      onClick={() => {
        setLeaving(true);
        window.setTimeout(onDone, 350);
      }}
      role="presentation"
    >
      {/* Image — same painting as the marketing hero. The scrims used to
          live inside this container; they're now siblings rendered with
          the text so the painting reads clean during its solo entrance. */}
      <div className="absolute inset-0 animate-splash-image">
        <img
          src={krishnaArjuna}
          alt=""
          className="w-full h-full object-cover"
          draggable={false}
        />
      </div>

      {/* Scrims appear with the text, not before. Both use the same
          opacity-only animation so they're locked together perceptually. */}
      {showText && (
        <>
          <div
            className="splash-top-fade animate-splash-content"
            aria-hidden
          />
          <div
            className="splash-fade animate-splash-content"
            aria-hidden
          />
        </>
      )}

      {/* Content — bottom-left, same composition as the hero. */}
      <div className="relative z-10 h-full flex flex-col px-8 lg:px-12 pb-12 lg:pb-16">
        <div className="flex-1" />

        {showText && (
          <h1 className="max-w-[18ch] font-display font-light text-page leading-[0.92] text-[clamp(2.4rem,6.5vw,5.25rem)] animate-splash-content">
            Every conversation
            <br />
            <span className="italicize text-flame-ember">deserves</span> a
            <br />
            charioteer.
          </h1>
        )}
      </div>
    </div>
  );
}
