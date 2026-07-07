"use client";
import * as React from "react";
import { THEMES, DEFAULT_THEME, STATIC_VARS } from "@/lib/themes";

interface ThemeCtx {
  themeId: string;
  setThemeId: (id: string) => void;
}
const Ctx = React.createContext<ThemeCtx>({ themeId: DEFAULT_THEME, setThemeId: () => {} });
export const useTheme = () => React.useContext(Ctx);

const STORAGE_KEY = "aegis-theme";

function applyTheme(id: string) {
  const theme = THEMES.find((t) => t.id === id) ?? THEMES[0];
  const root = document.documentElement;
  const vars = { ...STATIC_VARS, ...theme.vars };
  for (const [k, val] of Object.entries(vars)) root.style.setProperty(k, val);
  root.setAttribute("data-theme", theme.id);
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [themeId, setThemeIdState] = React.useState(DEFAULT_THEME);

  React.useEffect(() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    const initial = saved && THEMES.some((t) => t.id === saved) ? saved : DEFAULT_THEME;
    setThemeIdState(initial);
    applyTheme(initial);
  }, []);

  const setThemeId = React.useCallback((id: string) => {
    setThemeIdState(id);
    applyTheme(id);
    try { localStorage.setItem(STORAGE_KEY, id); } catch {}
  }, []);

  return <Ctx.Provider value={{ themeId, setThemeId }}>{children}</Ctx.Provider>;
}
