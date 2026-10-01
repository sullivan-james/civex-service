import { useSyncExternalStore } from 'react'
import {
  schemasApi,
  type FieldTypeDescriptor,
  type FieldTypes,
} from '../api/schemas'

/**
 * The field-type descriptors (`GET /schemas/field-types`): what each type is
 * and which rules it can carry. They never change while the server runs, so
 * they are fetched once and shared. This is a small external store rather
 * than a query so that components deep in the record form (`DynamicField`)
 * can read it without needing a query provider; until it loads, or if the
 * request fails, `useFieldTypes()` is null and callers fall back to their
 * built-in behaviour.
 */
let current: FieldTypes | null = null
let started = false
const listeners = new Set<() => void>()

function load() {
  if (started) return
  started = true
  schemasApi
    .fieldTypes()
    .then((data) => {
      current = data
      listeners.forEach((l) => l())
    })
    .catch(() => {
      started = false // try again the next time something asks
    })
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  load()
  return () => {
    listeners.delete(listener)
  }
}

export function useFieldTypes(): FieldTypes | null {
  return useSyncExternalStore(subscribe, () => current)
}

export function useFieldTypeDescriptor(
  type: string,
): FieldTypeDescriptor | undefined {
  return useFieldTypes()?.types.find((t) => t.type === type)
}

/** For tests: seed or clear the shared descriptors. */
export function setFieldTypesForTest(data: FieldTypes | null) {
  current = data
  started = data !== null
  listeners.forEach((l) => l())
}
