import type { Config } from "tailwindcss";
import defaultTheme from "tailwindcss/defaultTheme";

/**
 * Design tokens migrated from the legacy index.html CSS and formalized:
 * fonts Bebas Neue + Geologica, verdict colors red/green/amber.
 * All components MUST reference these tokens — no hardcoded hex values.
 */
const config: Config = {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Geologica", ...defaultTheme.fontFamily.sans],
        display: ["'Bebas Neue'", ...defaultTheme.fontFamily.sans],
      },
      colors: {
        verdict: {
          fake: "#ff2d55",
          original: "#34c759",
          suspect: "#ff9f0a",
          info: "#007aff",
        },
        surface: {
          light: "rgb(var(--surface-light) / <alpha-value>)",
          DEFAULT: "rgb(var(--surface) / <alpha-value>)",
          raised: "rgb(var(--surface-raised) / <alpha-value>)",
          dark: "rgb(var(--surface-dark) / <alpha-value>)",
        },
        ink: {
          DEFAULT: "rgb(var(--ink) / <alpha-value>)",
          muted: "rgb(var(--ink-muted) / <alpha-value>)",
        },
        line: "rgb(var(--line) / <alpha-value>)",
      },
      keyframes: {
        pulse: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
      },
      animation: {
        "logo-pulse": "pulse 2s infinite",
      },
    },
  },
  plugins: [],
};

export default config;
