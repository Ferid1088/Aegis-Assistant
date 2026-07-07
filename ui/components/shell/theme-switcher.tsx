"use client";
import { THEMES } from "@/lib/themes";
import { useTheme } from "./theme-provider";
import { cn } from "@/lib/utils";

// The stack of color dots at the bottom of the sidebar. Clicking one recolors
// the whole UI (via CSS variables) and persists the choice.
export function ThemeSwitcher() {
  const { themeId, setThemeId } = useTheme();
  return (
    <div className="flex flex-col items-center gap-2 py-2" role="radiogroup" aria-label="Color theme">
      {THEMES.map((t) => {
        const active = t.id === themeId;
        return (
          <button
            key={t.id}
            role="radio"
            aria-checked={active}
            aria-label={t.label}
            title={t.label}
            onClick={() => setThemeId(t.id)}
            className={cn(
              "h-3.5 w-3.5 rounded-full ring-offset-1 ring-offset-surface transition-transform hover:scale-110",
              active && "ring-2 ring-ink/40 scale-110"
            )}
            style={{ backgroundColor: t.swatch }}
          />
        );
      })}
    </div>
  );
}
