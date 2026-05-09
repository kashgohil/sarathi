/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Match the marketing-site palette — single source of truth for the
        // Sarathi product look.
        night: {
          DEFAULT: "#0A0F26",
          deep: "#060A1B",
          rise: "#131A3A",
          glow: "#1E2654",
        },
        flame: {
          DEFAULT: "#E5A752",
          deep: "#C58633",
          ember: "#F4C97A",
        },
        sindoor: {
          DEFAULT: "#C13D2A",
          deep: "#9A2B1C",
        },
        page: {
          DEFAULT: "#EDE3CC",
          dim: "rgba(237, 227, 204, 0.72)",
          ghost: "rgba(237, 227, 204, 0.42)",
          faint: "rgba(237, 227, 204, 0.20)",
          rule: "rgba(237, 227, 204, 0.12)",
        },
      },
      fontFamily: {
        // Cormorant Garamond for display, Plus Jakarta Sans for body,
        // JetBrains Mono for code/status.
        display: ["'Cormorant Garamond'", "ui-serif", "Georgia", "serif"],
        sans: ["'Plus Jakarta Sans'", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      letterSpacing: {
        wider2: "0.22em",
      },
      animation: {
        "splash-image":
          "splashImage 900ms cubic-bezier(0.2, 0.7, 0.2, 1) both",
        // Single shared animation for the text headline AND the scrims —
        // pure opacity, no transform, so nothing reflows or shifts during
        // the entrance and the elements are perfectly locked together.
        "splash-content":
          "splashContent 900ms cubic-bezier(0.2, 0.7, 0.2, 1) both",
        "splash-out":
          "splashOut 600ms cubic-bezier(0.4, 0.0, 0.6, 1) both",
        // Indeterminate shimmer for the Setup row's progress bar — used
        // when the download has started but no byte count has arrived
        // yet, so the user gets motion-feedback that something's happening.
        "progress-shimmer":
          "progressShimmer 1.4s ease-in-out infinite",
      },
      keyframes: {
        splashImage: {
          "0%": { opacity: "0", transform: "scale(1.06)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        splashContent: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        splashOut: {
          "0%": { opacity: "1", transform: "scale(1)" },
          "100%": { opacity: "0", transform: "scale(1.04)" },
        },
        progressShimmer: {
          "0%": { left: "-33%" },
          "100%": { left: "100%" },
        },
      },
    },
  },
  plugins: [],
};
