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
 * Active default while the Tailwind/dual-theme migration is in progress.
 * Dark keeps every not-yet-migrated screen (designed for the dark palette)
 * rendering exactly as before. An explicit user choice still wins. Flip this
 * to 'light' in the final migration phase once all screens are ported — see
 * the `.dark` token block in index.css and the inline guard in index.html
 * (both must flip together).
 */
const MIGRATION_DEFAULT: Theme = 'dark';

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
  // NOTE: we intentionally do NOT follow `prefers-color-scheme` yet — a
  // light-preferring OS would render un-migrated dark screens broken during
  // the bridge. System preference is honoured once light becomes the default.
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
