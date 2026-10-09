/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Primary accent — vivid royal blue (Free-LLM style)
        brand: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e40af",
          900: "#1e3a8a",
        },
        // Deep navy surface stack
        night: "#070b16",       // page background base
        panel: "#0d1526",       // card surface
        panelsoft: "#111c33",   // raised / hover surface
        inset: "#0a1120",       // spec-box inset
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(59,130,246,0.45), 0 10px 40px -12px rgba(37,99,235,0.45)",
        card: "0 10px 30px -18px rgba(0,0,0,0.8)",
        "glow-violet": "0 0 0 1px rgba(139,92,246,0.45), 0 10px 40px -12px rgba(139,92,246,0.4)",
      },
      keyframes: {
        marquee: {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" },
        },
        fadein: {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseglow: {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
      },
      animation: {
        marquee: "marquee 30s linear infinite",
        fadein: "fadein 0.4s ease-out both",
        pulseglow: "pulseglow 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
