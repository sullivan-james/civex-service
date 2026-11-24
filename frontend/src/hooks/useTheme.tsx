import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'

export type ThemePreference = 'system' | 'light' | 'dark'
type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'civex-theme'

function systemTheme(): ResolvedTheme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}

function readStoredPreference(): ThemePreference {
  const stored = localStorage.getItem(STORAGE_KEY)
  return stored === 'light' || stored === 'dark' ? stored : 'system'
}

function applyPreference(
  preference: ThemePreference,
  root: HTMLElement = document.documentElement,
) {
  if (preference === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', preference)
}

interface ThemeContextValue {
  preference: ThemePreference
  resolved: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

/** `target` and `scheme` are for a mounted app (`embed.tsx`): the theme is the
 * host's (`scheme`, or the browser's), set on the mounted element rather than
 * the page's `<html>`, and neither read from nor written to storage. */
export function ThemeProvider({
  children,
  target,
  scheme,
}: {
  children: ReactNode
  target?: HTMLElement
  scheme?: 'light' | 'dark'
}) {
  const [preference, setPreferenceState] = useState<ThemePreference>(() =>
    target ? (scheme ?? 'system') : readStoredPreference(),
  )
  // Only tracks the OS setting; combined with `preference` below to derive
  // `resolved` during render instead of mirroring it into more state.
  const [systemIsDark, setSystemIsDark] = useState(
    () => systemTheme() === 'dark',
  )

  useEffect(() => {
    applyPreference(preference, target)
  }, [preference, target])

  useEffect(() => {
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setSystemIsDark(mql.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  const resolved: ResolvedTheme =
    preference === 'system' ? (systemIsDark ? 'dark' : 'light') : preference

  function setPreference(next: ThemePreference) {
    if (!target) {
      if (next === 'system') localStorage.removeItem(STORAGE_KEY)
      else localStorage.setItem(STORAGE_KEY, next)
    }
    setPreferenceState(next)
  }

  return (
    <ThemeContext.Provider value={{ preference, resolved, setPreference }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider')
  return ctx
}
