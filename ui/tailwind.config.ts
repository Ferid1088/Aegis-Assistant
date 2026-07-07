import type { Config } from "tailwindcss";

// Colors read from CSS variables so the active theme (set on <html data-theme>)
// recolors the entire UI at runtime. Variable values live in lib/themes.ts and
// are applied by the ThemeProvider. Status hues are theme-independent.
const v = (name: string) => `var(${name})`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: v("--canvas"),
        surface: v("--surface"),
        surfaceMuted: v("--surface-muted"),
        line: v("--line"),
        lineStrong: v("--line-strong"),
        ink: v("--ink"),
        inkSoft: v("--ink-soft"),
        inkFaint: v("--ink-faint"),
        accent: v("--accent"),
        accentSoft: v("--accent-soft"),
        accentWash: v("--accent-wash"),
        // semantic status — constant across themes
        online: v("--online"),
        onlineWash: v("--online-wash"),
        degraded: v("--degraded"),
        offline: v("--offline"),
        offlineWash: v("--offline-wash"),
        info: v("--info"),
        infoWash: v("--info-wash"),
        role: v("--role"),
        roleWash: v("--role-wash"),
      },
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: { card: "10px", pill: "999px" },
      boxShadow: {
        card: "0 1px 2px rgba(0,0,0,0.04), 0 1px 1px rgba(0,0,0,0.03)",
        raised: "0 4px 16px rgba(0,0,0,0.08)",
      },
      fontSize: { eyebrow: ["11px", { lineHeight: "1.4", letterSpacing: "0.08em" }] },
    },
  },
  plugins: [],
};
export default config;
