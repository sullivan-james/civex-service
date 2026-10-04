import { useEffect } from 'react'
import { APP_NAME, formatTitle } from '../utils/documentTitle'

/** Put `parts` (most specific first) in the browser tab's title, and put the
 * plain app name back when the page goes away, so a page that sets nothing
 * never shows the previous page's title. */
export function useDocumentTitle(
  parts: ReadonlyArray<string | null | undefined | false>,
): void {
  const title = formatTitle(parts)
  useEffect(() => {
    document.title = title
    return () => {
      document.title = APP_NAME
    }
  }, [title])
}
