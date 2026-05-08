import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Krishna's hour: midnight indigo, deep, never pure black.
        night: {
          DEFAULT: "#0A0F26",
          deep: "#060A1B",
          rise: "#131A3A",
          glow: "#1E2654",
        },
        // Lamp-flame on brass: saffron-gold for warmth and emphasis.
        flame: {
          DEFAULT: "#E5A752",
          deep: "#C58633",
          ember: "#F4C97A",
        },
        // Sindoor: ritual punctuation, used like full stops.
        sindoor: {
          DEFAULT: "#C13D2A",
          deep: "#9A2B1C",
        },
        // Parchment: cream text laid over the night.
        page: {
          DEFAULT: "#EDE3CC",
          dim: "rgba(237, 227, 204, 0.72)",
          ghost: "rgba(237, 227, 204, 0.42)",
          faint: "rgba(237, 227, 204, 0.20)",
          rule: "rgba(237, 227, 204, 0.12)",
        },
      },
      fontFamily: {
        // Display serif with dramatic italic: Cormorant Garamond.
        display: ["var(--font-display)", "ui-serif", "Georgia", "serif"],
        // Humanist sans for body, less common than Inter.
        sans: ["var(--font-body)", "ui-sans-serif", "system-ui"],
        // Devanagari display — hand-painted poster face.
        devanagari: ["var(--font-deva)", "var(--font-display)", "serif"],
        // Gujarati body / display.
        gu: ["var(--font-gu)", "var(--font-deva)", "serif"],
        // Mono for status, detail, and the colophon.
        mono: ["var(--font-mono)", "ui-monospace", "Menlo", "monospace"],
      },
      letterSpacing: {
        wider2: "0.22em",
      },
      fontSize: {
        "display-xl": [
          "clamp(4rem, 11vw, 9.5rem)",
          { lineHeight: "0.92", letterSpacing: "-0.035em" },
        ],
        "display-lg": [
          "clamp(2.75rem, 7vw, 5.75rem)",
          { lineHeight: "0.96", letterSpacing: "-0.025em" },
        ],
        "display-md": [
          "clamp(1.75rem, 4vw, 3.25rem)",
          { lineHeight: "1.04", letterSpacing: "-0.015em" },
        ],
      },
      animation: {
        rise: "rise 1.05s cubic-bezier(0.16, 0.84, 0.32, 1) both",
        wheel: "wheel 80s linear infinite",
        ticker: "ticker 56s linear infinite",
      },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(20px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        wheel: {
          "0%": { transform: "rotate(0deg)" },
          "100%": { transform: "rotate(360deg)" },
        },
        ticker: {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
