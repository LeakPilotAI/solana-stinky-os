import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: "#050605",
          panel: "#0c0f0c",
          elevated: "#121812",
          border: "#1a2a1a",
          muted: "#6b7a6b",
          text: "#e8f0e8",
          dim: "#9aab9a",
          /* Acid green — primary accent */
          accent: "#39ff14",
          accentDim: "#1db800",
          accentSoft: "#39ff1422",
          warn: "#f0c000",
          danger: "#ff3b3b",
          info: "#3dd6ff",
        },
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "monospace"],
      },
      fontSize: {
        "2xs": ["0.65rem", { lineHeight: "0.9rem" }],
      },
      boxShadow: {
        glow: "0 0 20px rgba(57, 255, 20, 0.15)",
        "glow-sm": "0 0 10px rgba(57, 255, 20, 0.12)",
      },
    },
  },
  plugins: [],
};

export default config;
