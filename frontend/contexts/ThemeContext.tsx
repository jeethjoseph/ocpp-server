'use client';

import {
  createContext,
  useContext,
  useEffect,
  useSyncExternalStore,
} from 'react';

type Theme = 'light' | 'dark' | 'system';

interface ThemeContextType {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  actualTheme: 'light' | 'dark';
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

// Mobile Safari (private mode / ITP / "Block All Cookies") throws
// `SecurityError: The operation is insecure.` on ANY localStorage access,
// not just writes. Reads and writes must be guarded so the provider never
// crashes during render — theme falls back to in-memory state when storage
// is unavailable (it just won't persist across reloads).
function readStoredTheme(): Theme | null {
  try {
    return localStorage.getItem('theme') as Theme | null;
  } catch {
    return null;
  }
}

function writeStoredTheme(theme: Theme): void {
  try {
    localStorage.setItem('theme', theme);
  } catch {
    // Storage blocked — keep the selection for this session only.
  }
}

// The stored preference and the OS colour scheme are both *external stores*.
// Syncing them into React state from an effect is what react-hooks/
// set-state-in-effect flags, and a lazy useState initialiser would read
// localStorage during the first client render and desync from the
// prerendered HTML. useSyncExternalStore handles both: it reads the live
// value after mount and uses an explicit server snapshot during SSR and
// hydration, so the server and first client render agree on system/light.
const themeListeners = new Set<() => void>();

// Mirrors the last selection in memory so the provider still re-renders when
// localStorage is blocked and the write above is a no-op.
let inMemoryTheme: Theme | null = null;

function subscribeStoredTheme(onChange: () => void): () => void {
  themeListeners.add(onChange);
  return () => {
    themeListeners.delete(onChange);
  };
}

function getStoredThemeSnapshot(): Theme {
  return inMemoryTheme ?? readStoredTheme() ?? 'system';
}

function getServerThemeSnapshot(): Theme {
  return 'system';
}

function subscribeSystemTheme(onChange: () => void): () => void {
  const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
  mediaQuery.addEventListener('change', onChange);
  return () => mediaQuery.removeEventListener('change', onChange);
}

function getSystemThemeSnapshot(): 'light' | 'dark' {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

function getServerSystemThemeSnapshot(): 'light' | 'dark' {
  return 'light';
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useSyncExternalStore(
    subscribeStoredTheme,
    getStoredThemeSnapshot,
    getServerThemeSnapshot
  );
  const systemTheme = useSyncExternalStore(
    subscribeSystemTheme,
    getSystemThemeSnapshot,
    getServerSystemThemeSnapshot
  );

  const actualTheme: 'light' | 'dark' =
    theme === 'system' ? systemTheme : theme;

  const setTheme = (next: Theme): void => {
    inMemoryTheme = next;
    writeStoredTheme(next);
    themeListeners.forEach((listener) => listener());
  };

  // Applying the attribute is a DOM side effect, not state — this stays an
  // effect and runs whenever the resolved theme changes.
  useEffect(() => {
    const root = document.documentElement;
    if (actualTheme === 'dark') {
      root.setAttribute('data-theme', 'dark');
    } else {
      root.removeAttribute('data-theme');
    }
  }, [actualTheme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, actualTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
