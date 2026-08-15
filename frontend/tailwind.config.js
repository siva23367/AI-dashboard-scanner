/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          950: "#070c1f",
          900: "#0b1330",
          800: "#101a3f",
          700: "#1b2a63",
        },
        ink: "#0f1526",
        muted: "#687386",
        line: "#e5e9f0",
        bg: "#f5f7fb",
        signal: {
          blue: "#2b5fff",
          blueDark: "#1c46d6",
          mint: "#17b884",
          amber: "#e08a1e",
          coral: "#e0473f",
        },
      },
      fontFamily: {
        display: ["'Space Grotesk'", "sans-serif"],
        sans: ["'Inter'", "-apple-system", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(16,26,63,.04)",
        lift: "0 10px 30px rgba(11,19,48,.16)",
        hero: "0 10px 30px rgba(11,19,48,.25)",
      },
      borderRadius: {
        xl2: "18px",
      },
      keyframes: {
        sweep: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
        fadeUp: {
          "0%": { opacity: 0, transform: "translateY(6px)" },
          "100%": { opacity: 1, transform: "translateY(0)" },
        },
        pulseDot: {
          "0%, 100%": { opacity: 1 },
          "50%": { opacity: 0.35 },
        },
      },
      animation: {
        sweep: "sweep 1.6s ease-in-out infinite",
        fadeUp: "fadeUp .35s ease-out",
        pulseDot: "pulseDot 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
