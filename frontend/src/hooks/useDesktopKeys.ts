import { useEffect } from 'react'

export type DesktopKeyAction = 'reload' | 'back' | 'forward'

type Keys = Pick<
  KeyboardEvent,
  'key' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey'
>

/** What a key press means in the desktop app, which (unlike a browser) has no
 * reload or back of its own: pywebview turns WebView2's keys off on Windows,
 * and WKWebView on macOS never had them. The usual keys for each platform:
 * F5 / Ctrl+R (Cmd+R on a Mac) reload, Alt+Left / Alt+Right (Cmd+[ / Cmd+]
 * on a Mac) go back and forward. */
export function desktopKeyAction(
  e: Keys,
  mac: boolean,
): DesktopKeyAction | null {
  const key = e.key
  const command = mac ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey
  if (key === 'F5' && !e.altKey) return 'reload'
  if (command && !e.altKey && key.toLowerCase() === 'r') return 'reload'
  if (mac) {
    if (command && !e.shiftKey && !e.altKey && key === '[') return 'back'
    if (command && !e.shiftKey && !e.altKey && key === ']') return 'forward'
    return null
  }
  // Alt+Left is word-jumping on a Mac, so only off the Mac.
  if (e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
    if (key === 'ArrowLeft') return 'back'
    if (key === 'ArrowRight') return 'forward'
  }
  return null
}

const isMac = () =>
  typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform)

/** Reload, back and forward from the keyboard in the desktop app. Does nothing
 * in a browser, which has its own. `window.pywebview` is checked at each press,
 * not once, because pywebview may inject it after the page has loaded. */
export function useDesktopKeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!window.pywebview || e.defaultPrevented) return
      const action = desktopKeyAction(e, isMac())
      if (!action) return
      e.preventDefault()
      if (action === 'reload') window.location.reload()
      else if (action === 'back') window.history.back()
      else window.history.forward()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
