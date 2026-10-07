import { useSyncExternalStore } from 'react'

/** Whether this page is inside the civex desktop app (pywebview).
 *
 * pywebview adds `window.pywebview` only after the page has loaded (on
 * Windows noticeably later than on macOS) and then fires `pywebviewready`, so
 * this is read live: deciding once while the page loaded left the Windows app
 * without its project menu and its native folder picker. */
export function isDesktopNow(): boolean {
  return typeof window !== 'undefined' && !!window.pywebview
}

function subscribe(onChange: () => void) {
  window.addEventListener('pywebviewready', onChange)
  return () => window.removeEventListener('pywebviewready', onChange)
}

export function useIsDesktop(): boolean {
  return useSyncExternalStore(subscribe, isDesktopNow, () => false)
}
