// Theme definitions. Each theme is a full token set applied via CSS variables
// on <html data-theme>. The color dots in the sidebar switch the active theme;
// every component reads colors through Tailwind tokens that map to these vars,
// so a single switch recolors the entire UI.

export interface Theme {
  id: string;
  label: string;
  swatch: string; // the dot color shown in the rail
  vars: Record<string, string>;
}

// Token keys mirror tailwind.config colors (canvas, surface, ink, accent, …).
export const THEMES: Theme[] = [
  {
    id: "ochre",
    label: "Ochre (default)",
    swatch: "#B08320",
    vars: {
      "--canvas": "#F3EEE3", "--surface": "#FBF8F1", "--surface-muted": "#EFE9DC",
      "--line": "#E2DAC9", "--line-strong": "#D3C8B2",
      "--ink": "#2B2620", "--ink-soft": "#6B6459", "--ink-faint": "#9A9284",
      "--accent": "#B08320", "--accent-soft": "#C79A3A", "--accent-wash": "#EFE1BE",
    },
  },
  {
    id: "sage",
    label: "Sage",
    swatch: "#5B8C51",
    vars: {
      "--canvas": "#EEF1E9", "--surface": "#F8FAF4", "--surface-muted": "#E4E9DB",
      "--line": "#D6DECB", "--line-strong": "#C2CCB2",
      "--ink": "#242A20", "--ink-soft": "#5A6153", "--ink-faint": "#8B927F",
      "--accent": "#5B8C51", "--accent-soft": "#71A166", "--accent-wash": "#D9E7CF",
    },
  },
  {
    id: "violet",
    label: "Violet",
    swatch: "#7A5EA8",
    vars: {
      "--canvas": "#F0ECF4", "--surface": "#FAF7FC", "--surface-muted": "#E7E0EE",
      "--line": "#DCD3E6", "--line-strong": "#C9BCD6",
      "--ink": "#28222E", "--ink-soft": "#605769", "--ink-faint": "#948A9E",
      "--accent": "#7A5EA8", "--accent-soft": "#9077BC", "--accent-wash": "#E4DCF0",
    },
  },
  {
    id: "slate",
    label: "Slate",
    swatch: "#4E6E8E",
    vars: {
      "--canvas": "#ECEEF1", "--surface": "#F7F9FB", "--surface-muted": "#E1E5EA",
      "--line": "#D3D9E0", "--line-strong": "#BCC5CF",
      "--ink": "#20262C", "--ink-soft": "#525C66", "--ink-faint": "#828C97",
      "--accent": "#4E6E8E", "--accent-soft": "#6486A6", "--accent-wash": "#D9E3EC",
    },
  },
  {
    id: "clay",
    label: "Clay",
    swatch: "#B0553A",
    vars: {
      "--canvas": "#F4EBE6", "--surface": "#FCF6F2", "--surface-muted": "#EDDFD8",
      "--line": "#E4D2C8", "--line-strong": "#D6BCAE",
      "--ink": "#2E211B", "--ink-soft": "#6B564D", "--ink-faint": "#9C877D",
      "--accent": "#B0553A", "--accent-soft": "#C56E52", "--accent-wash": "#EDD3C8",
    },
  },
];

export const DEFAULT_THEME = THEMES[0].id;

// status colors stay constant across themes (semantics shouldn't shift hue)
export const STATIC_VARS: Record<string, string> = {
  "--online": "#5B8C51", "--online-wash": "#DCE7D3",
  "--degraded": "#B08320",
  "--offline": "#B0553A", "--offline-wash": "#EAD5CC",
  "--info": "#4E6E8E", "--info-wash": "#D9E3EC",
  "--role": "#7A5EA8", "--role-wash": "#E4DCF0",
};

export function themeStyleString(theme: Theme): string {
  const all = { ...STATIC_VARS, ...theme.vars };
  return Object.entries(all).map(([k, v]) => `${k}:${v}`).join(";");
}
