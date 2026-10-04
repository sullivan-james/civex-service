/** What the browser tab says. The app name is always last, so tabs from this
 * app sort together and the part that tells them apart comes first, where a
 * narrow tab still shows it. */
export const APP_NAME = 'civex'

const SEPARATOR = ' · '
const MAX_PART = 40
/** The current thing, then up to this many of what it sits inside. */
const MAX_PARTS = 3

const clip = (text: string) =>
  text.length > MAX_PART ? `${text.slice(0, MAX_PART - 1).trimEnd()}…` : text

/** "Selection 12 · study · civex": the parts that are there, long ones
 * clipped, the same name never twice in a row, then the app name. */
export function formatTitle(
  parts: ReadonlyArray<string | null | undefined | false>,
): string {
  const kept: string[] = []
  for (const part of parts) {
    const text = typeof part === 'string' ? part.trim() : ''
    if (text && text !== kept[kept.length - 1]) kept.push(clip(text))
  }
  return [...kept.slice(0, MAX_PARTS), APP_NAME].join(SEPARATOR)
}

/** The parts of a page's tab title, most specific first: what the page is (its
 * title if that is plain text, else the last item of its trail) and then what
 * it sits inside, nearest first. A record is "Sample 12 · parent · study". */
export function pageTitleParts(
  title: unknown,
  trail: ReadonlyArray<{ label: string }> | undefined,
): string[] {
  const labels = (trail ?? []).map((c) => c.label)
  const current = typeof title === 'string' ? title : labels[labels.length - 1]
  const inside = labels.slice(0, -1).reverse()
  return [current, ...inside].filter(
    (p): p is string => typeof p === 'string' && p.trim() !== '',
  )
}
