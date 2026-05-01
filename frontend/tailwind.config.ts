import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  // Class-based dark mode: <html class="dark"> turns it on. The bootstrap
  // script in index.html sets this before React hydrates.
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "Menlo", "monospace"],
      },
      colors: {
        // Pharos light theme inspired by Feedly's clean editorial look
        ink: {
          50: "#fafafa",
          100: "#f4f4f5",
          200: "#e4e4e7",
          300: "#d4d4d8",
          400: "#a1a1aa",
          500: "#71717a",
          600: "#52525b",
          700: "#3f3f46",
          800: "#27272a",
          900: "#18181b",
          950: "#09090b",
        },
        beam: {
          DEFAULT: "#2563eb",
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
        warm: {
          50: "#fffbeb",
          100: "#fef3c7",
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
        },
        danger: {
          50: "#fef2f2",
          100: "#fee2e2",
          200: "#fecaca",
          400: "#f87171",
          500: "#ef4444",
          600: "#dc2626",
          700: "#b91c1c",
          800: "#991b1b",
          900: "#7f1d1d",
        },
        good: {
          50: "#f0fdf4",
          100: "#dcfce7",
          400: "#4ade80",
          500: "#22c55e",
          600: "#16a34a",
        },
        // Brand palette extracted from the Pharos lighthouse logo. Used
        // primarily by dark mode (deep navy surfaces + gold accents) but
        // available everywhere via `bg-pharos-navy-*` / `text-pharos-gold-*`.
        pharos: {
          // Near-black surfaces with a subtle navy undertone (matches the
          // brand mark's background plate). Pulled noticeably darker than
          // a typical "dark navy" so cards feel inky, not blue.
          navy: {
            50:  "#dadde3",
            100: "#a9aebd",
            200: "#717689",
            300: "#3d4458",
            400: "#1c2233",
            500: "#10141f",  // border / divider in dark mode
            600: "#0a0d16",  // hover surface in dark mode
            700: "#070a11",  // card / sidebar / topbar in dark mode
            800: "#04060c",  // body bg in dark mode
            900: "#020308",
            950: "#000000",
          },
          // Lighthouse-beam gold (accent)
          gold: {
            50:  "#fff8e7",
            100: "#feeab2",
            200: "#fbd97a",
            300: "#f7c747",
            400: "#f4b84a",
            500: "#e8a93c",  // primary brand gold
            600: "#c98a2a",
            700: "#9e6b1f",
            800: "#704a16",
            900: "#3f2a0d",
          },
        },
      },
      boxShadow: {
        soft: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 3px 0 rgb(0 0 0 / 0.06)",
        card: "0 1px 3px 0 rgb(0 0 0 / 0.05), 0 4px 12px -2px rgb(0 0 0 / 0.05)",
      },
      animation: {
        "fade-in": "fadeIn 200ms ease-out",
        "slide-up": "slideUp 200ms ease-out",
      },
      keyframes: {
        fadeIn: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [typography],
} satisfies Config;
