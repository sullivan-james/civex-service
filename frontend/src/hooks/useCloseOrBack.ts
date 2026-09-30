import { useNavigate } from 'react-router'

/**
 * For pages meant to be opened in a new tab (editors launched via
 * `target="_blank"`): closes the tab if it has an opener to return to
 * (`window.opener` — set when this tab was actually spawned by a link/
 * `window.open` from elsewhere in the app), otherwise navigates back to
 * `fallbackPath` in place — covers a direct visit, a refresh, or a browser
 * that opened the link in the current tab instead of a new one.
 */
export function useCloseOrBack(fallbackPath: string) {
  const navigate = useNavigate()
  return () => {
    if (window.opener) {
      window.close()
    } else {
      navigate(fallbackPath)
    }
  }
}
