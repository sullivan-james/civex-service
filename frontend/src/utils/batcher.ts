/** Turns many `load(key)` calls made close together into one `fetchBatch`.
 *
 * Anything that shows a name for an id (a table with a record column, a list of
 * runs) asks for each id where it is drawn, which is simple to write and, done
 * naively, one request per row. Here every ask made within `wait` ms joins the
 * same request, so a screen of fifty rows costs one. The same key asked twice
 * in a window is fetched once. A batch is split at `max` keys.
 *
 * `fetchBatch` returns what it found, by key; a key it doesn't return resolves
 * to `undefined` (it isn't there), which is not an error. If it throws, every
 * waiting `load` rejects. */
export function createBatcher<K extends string, V>(
  fetchBatch: (keys: K[]) => Promise<Map<K, V>>,
  { wait = 10, max = 100 }: { wait?: number; max?: number } = {},
) {
  let waiting = new Map<
    K,
    { resolve: (v: V | undefined) => void; reject: (e: unknown) => void }[]
  >()
  let timer: ReturnType<typeof setTimeout> | null = null

  async function flush() {
    const batch = waiting
    waiting = new Map()
    timer = null
    const keys = [...batch.keys()]
    for (let i = 0; i < keys.length; i += max) {
      const chunk = keys.slice(i, i + max)
      try {
        const found = await fetchBatch(chunk)
        for (const key of chunk)
          for (const w of batch.get(key) ?? []) w.resolve(found.get(key))
      } catch (err) {
        for (const key of chunk)
          for (const w of batch.get(key) ?? []) w.reject(err)
      }
    }
  }

  return {
    load(key: K): Promise<V | undefined> {
      return new Promise((resolve, reject) => {
        const list = waiting.get(key) ?? []
        list.push({ resolve, reject })
        waiting.set(key, list)
        if (timer === null) timer = setTimeout(flush, wait)
      })
    },
  }
}
