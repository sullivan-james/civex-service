import { useCallback } from 'react'
import { useSearchParams } from 'react-router'

export type SortParam = { field: string; dir: 'asc' | 'desc' }

/** Search text, a few dropdown choices, a sort and a page for a simple list
 * (runs, history), held in the address so the view can be linked and Back
 * works. `ns` prefixes the names when a page has two lists; `picks` names the
 * dropdowns. Changing anything but the page returns to page one. */
export function useListParams(ns: string, picks: string[], pageSize = 25) {
  const [sp, setSp] = useSearchParams()
  const [field = '', dir = 'asc'] = (sp.get(`${ns}sort`) ?? '').split(':')
  const page = Math.max(0, Number(sp.get(`${ns}page`) ?? 1) - 1) || 0
  const size = Number(sp.get(`${ns}size`)) || pageSize

  const set = useCallback(
    (patch: Record<string, string | number | undefined>) =>
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev)
          const keys = Object.keys(patch)
          if (!keys.includes('page')) next.delete(`${ns}page`)
          for (const k of keys) {
            const v = patch[k]
            const value = k === 'page' && typeof v === 'number' ? v + 1 : v
            if (
              value === undefined ||
              value === '' ||
              (value === 1 && k === 'page')
            )
              next.delete(`${ns}${k}`)
            else next.set(`${ns}${k}`, String(value))
          }
          return next
        },
        { replace: true },
      ),
    [setSp, ns],
  )

  return {
    q: sp.get(`${ns}q`) ?? '',
    sort: field
      ? ({ field, dir: dir === 'desc' ? 'desc' : 'asc' } as SortParam)
      : null,
    /** The sort as the API takes it: `column:direction`, or undefined. */
    sortParam: field
      ? `${field}:${dir === 'desc' ? 'desc' : 'asc'}`
      : undefined,
    page,
    size,
    picks: Object.fromEntries(picks.map((k) => [k, sp.get(`${ns}${k}`) ?? ''])),
    set,
    /** Click-through for a column header: ascending, descending, off. */
    toggleSort: (key: string) =>
      set({
        sort:
          field !== key
            ? `${key}:asc`
            : dir === 'asc'
              ? `${key}:desc`
              : undefined,
      }),
  }
}
