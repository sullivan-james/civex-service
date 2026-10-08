import { useEffect, useSyncExternalStore } from 'react'

/** How large the interface is drawn, as a percentage of the normal size:
 * Settings → Appearance → Size, and ⌘/Ctrl with + − 0 in the desktop app.
 *
 * It scales the root font size, which nearly everything is sized from, rather
 * than using CSS `zoom` (which misplaces menus and tooltips in WebKit). A
 * per-window convenience in localStorage: losing it only means normal size. */
export const UI_SIZES = [80, 90, 100, 110, 125] as const
export type UiSize = (typeof UI_SIZES)[number]
const NORMAL: UiSize = 100
const STORAGE_KEY = 'civex-ui-size'
const CHANGE_EVENT = 'civex-ui-size'

function read(): UiSize {
  try {
    const stored = Number(localStorage.getItem(STORAGE_KEY))
    return (UI_SIZES as readonly number[]).includes(stored)
      ? (stored as UiSize)
      : NORMAL
  } catch {
    return NORMAL
  }
}

/** Draw the interface at the stored size: called once before the first
 * render, so a page never flashes at the normal size first. */
export function applyUiSize(size: UiSize = read()) {
  document.documentElement.style.fontSize = size === NORMAL ? '' : `${size}%`
}

export function setUiSize(size: UiSize) {
  try {
    if (size === NORMAL) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, String(size))
  } catch {
    // Storage blocked: the size lasts this page only.
  }
  applyUiSize(size)
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

/** One step larger (+1) or smaller (−1), or back to normal (0). */
export function stepUiSize(direction: -1 | 0 | 1) {
  if (direction === 0) return setUiSize(NORMAL)
  const at = UI_SIZES.indexOf(read())
  const next = Math.min(UI_SIZES.length - 1, Math.max(0, at + direction))
  setUiSize(UI_SIZES[next])
}

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGE_EVENT, onChange)
  window.addEventListener('storage', onChange)
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange)
    window.removeEventListener('storage', onChange)
  }
}

export function useUiSize(): UiSize {
  return useSyncExternalStore(subscribe, read)
}

/** ⌘/Ctrl with + − 0 in the desktop app, whose window (a bare web view)
 * ignores them; in a browser they are left to the browser's own zoom. */
export function useDesktopZoomKeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return
      if (!(window as { pywebview?: unknown }).pywebview) return
      const direction =
        e.key === '=' || e.key === '+'
          ? 1
          : e.key === '-' || e.key === '_'
            ? -1
            : e.key === '0'
              ? 0
              : null
      if (direction === null) return
      e.preventDefault()
      stepUiSize(direction)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
