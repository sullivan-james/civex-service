import { useEffect, useMemo, useState } from 'react'
import { useCollections } from './useCollections'
import {
  readVisits,
  recordVisit,
  topCollections,
  VISITS_KEY,
} from '../utils/collectionVisits'

const VISIT_EVENT = 'civex:collection-visit'

/** Notes that `name` was opened, for the nav's "most used" list. */
export function recordCollectionVisit(name: string) {
  try {
    recordVisit(localStorage, name)
    window.dispatchEvent(new Event(VISIT_EVENT))
  } catch {
    /* no storage: nothing is remembered */
  }
}

/** The collections opened most often in this browser (see
 * utils/collectionVisits), for the nav. Refreshes when a collection is
 * opened here or in another tab. */
export function useFrequentCollections(limit = 5) {
  const { data: collections } = useCollections()
  const [visits, setVisits] = useState(() => {
    try {
      return readVisits(localStorage)
    } catch {
      return {}
    }
  })

  useEffect(() => {
    const refresh = () => {
      try {
        setVisits(readVisits(localStorage))
      } catch {
        /* keep what we have */
      }
    }
    const onStorage = (e: StorageEvent) => {
      if (e.key === VISITS_KEY) refresh()
    }
    window.addEventListener(VISIT_EVENT, refresh)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(VISIT_EVENT, refresh)
      window.removeEventListener('storage', onStorage)
    }
  }, [])

  return useMemo(() => {
    const byName = new Map((collections ?? []).map((c) => [c.name, c]))
    return topCollections(visits, [...byName.keys()], limit).map((name) =>
      byName.get(name)!,
    )
  }, [collections, visits, limit])
}
