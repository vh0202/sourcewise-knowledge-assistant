import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";

import { useMediaQuery } from "./hooks";

export type Theme = "light" | "dark";
/** What the visitor chose: an explicit theme, or "system" to follow the operating system. */
export type ThemePreference = Theme | "system";

// The same key is read by /theme-init.js, which applies the theme before the first paint.
const STORAGE_KEY = "sourcewise-theme";

interface ThemeState {
  theme: Theme;
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeState | null>(null);

function storedPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(storedPreference);
  const systemDark = useMediaQuery("(prefers-color-scheme: dark)");
  const theme: Theme = preference === "system" ? (systemDark ? "dark" : "light") : preference;

  // Apply the theme to <html>. Transitions are switched off for one frame so that the whole
  // interface changes at once instead of cross-fading element by element.
  useLayoutEffect(() => {
    const root = document.documentElement;
    if (root.dataset.theme === theme) return;
    root.classList.add("theme-switching");
    root.dataset.theme = theme;
    const frame = window.requestAnimationFrame(() => root.classList.remove("theme-switching"));
    return () => {
      window.cancelAnimationFrame(frame);
      root.classList.remove("theme-switching");
    };
  }, [theme]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    try {
      if (next === "system") window.localStorage.removeItem(STORAGE_KEY);
      else window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // The choice still applies for this visit.
    }
  }, []);

  // A choice made in another tab applies here too.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) setPreferenceState(storedPreference());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const toggle = useCallback(() => setPreference(theme === "dark" ? "light" : "dark"), [theme, setPreference]);

  const value = useMemo(() => ({ theme, preference, setPreference, toggle }), [theme, preference, setPreference, toggle]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside <ThemeProvider>");
  return value;
}
