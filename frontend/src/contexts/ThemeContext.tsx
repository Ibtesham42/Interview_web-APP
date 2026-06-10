import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'theme';

/**
 * Default theme when the user has made no explicit choice. Light is the
 * product default (Phase 5); an explicit stored choice still wins, and dark
 * remains a first-class theme via the ☀/☾ toggle. Must stay in sync with the
 * inline pre-paint guard in index.html (both default to light).
 *
 * Possible follow-up: honour `prefers-color-scheme` when no choice is stored
 * (read `window.matchMedia('(prefers-color-scheme: dark)')` in
 * readInitialTheme). Left out here to keep the flip minimal and predictable.
 */
const MIGRATION_DEFAULT: Theme = 'light';

interface ThemeContextValue {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

function readInitialTheme(): Theme {
  if (typeof window === 'undefined') return MIGRATION_DEFAULT;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    /* localStorage unavailable (private mode) — fall through to default */
  }
  // No stored choice → product default (light). System `prefers-color-scheme`
  // is not consulted (see MIGRATION_DEFAULT note for the optional follow-up).
  return MIGRATION_DEFAULT;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readInitialTheme);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle('dark', theme === 'dark');
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* ignore persistence failures */
    }
  }, [theme]);

  const setTheme = useCallback((next: Theme) => setThemeState(next), []);
  const toggleTheme = useCallback(
    () => setThemeState((prev) => (prev === 'dark' ? 'light' : 'dark')),
    [],
  );

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider');
  return ctx;
}
