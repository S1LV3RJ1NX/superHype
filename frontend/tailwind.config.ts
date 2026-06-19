import type { Config } from "tailwindcss";

// Colors map to the section 14 design tokens, exposed as HSL CSS variables in
// src/styles/globals.css so shadcn/ui components can be added later without
// re-theming. Named aliases (paper, sand, ink, clay, ok/pending/fail) carry the
// design-system vocabulary on top of the standard shadcn token names.
const config: Config = {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // Design-system aliases.
        paper: "hsl(var(--paper))",
        surface: "hsl(var(--surface))",
        sand: "hsl(var(--sand))",
        ink: "hsl(var(--ink))",
        "muted-ink": "hsl(var(--muted-ink))",
        clay: {
          DEFAULT: "hsl(var(--clay))",
          press: "hsl(var(--clay-press))",
        },
        ok: "hsl(var(--ok))",
        pending: "hsl(var(--pending))",
        fail: "hsl(var(--fail))",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        serif: ["Fraunces", "Newsreader", "ui-serif", "serif"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
