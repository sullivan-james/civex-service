import { useSyncExternalStore } from 'react'
import { settingsApi, type MapSettings } from '../api/settings'

/**
 * Where the location editor gets its street-level map, if anywhere. Shared
 * and fetched once, like the field-type descriptors, so the record form can
 * read it without a query provider. Null until loaded (or if there is no
 * server); the editor then draws its bundled coastlines only.
 */
let current: MapSettings | null = null
let started = false
const listeners = new Set<() => void>()

function load() {
  if (started) return
  started = true
  settingsApi
    .getMap()
    .then((s) => {
      current = s
      listeners.forEach((l) => l())
    })
    .catch(() => {
      started = false
    })
}

export function useMapSettings(): MapSettings | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      load()
      return () => {
        listeners.delete(l)
      }
    },
    () => current,
  )
}

/** After the setting is saved on the Settings page. */
export function setMapSettings(s: MapSettings) {
  current = s
  started = true
  listeners.forEach((l) => l())
}
