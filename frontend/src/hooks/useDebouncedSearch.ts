import { useEffect, useState } from 'react'

/** Search box text that is pushed to `commit` (the address) after a pause, and
 * follows the committed value when it changes from outside (Back, a cleared
 * filter). Returns the text and its setter. */
export function useDebouncedSearch(
  committed: string,
  commit: (q: string) => void,
  ms = 300,
) {
  const [text, setText] = useState(committed)
  const [seen, setSeen] = useState(committed)
  if (committed !== seen) {
    setSeen(committed)
    setText(committed)
  }
  useEffect(() => {
    if (text === committed) return
    const t = setTimeout(() => commit(text), ms)
    return () => clearTimeout(t)
  }, [text, committed, commit, ms])
  return [text, setText] as const
}
