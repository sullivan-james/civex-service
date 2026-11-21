import { targetKeys, type NavTarget } from './pins'
import { schemaRecordsPath } from './explorerState'

/** The shapes pins and recents are built from, in one place so every page
 * that offers a star describes the same thing the same way. */

export function collectionTarget(c: { id: string; name: string }): NavTarget {
  return {
    key: targetKeys.collection(c.id),
    kind: 'collection',
    label: c.name,
    to: `/collections/${c.id}`,
  }
}

export function recordTarget(r: {
  id: string
  natural_name: string | null
  schema_name: string
  /** Name of the collection it lives in, when known. */
  collection?: string | null
}): NavTarget {
  return {
    key: targetKeys.record(r.id),
    kind: 'record',
    label: r.natural_name ?? r.id.slice(0, 8),
    to: `/records/${r.id}`,
    context: r.collection
      ? `${r.schema_name} · ${r.collection}`
      : r.schema_name,
  }
}

export function viewTarget(
  schema: { id: string; name: string },
  viewName: string,
): NavTarget {
  return {
    key: targetKeys.view(schema.name, viewName),
    kind: 'view',
    saved: 'filter',
    label: viewName,
    to: schemaRecordsPath(schema.id, viewName),
    context: schema.name,
    schema: schema.name,
    view: viewName,
  }
}

/** A saved export: its own page, where it is changed and run. */
export function exportTarget(def: {
  schema_name: string
  name: string
}): NavTarget {
  return {
    key: `export:${def.schema_name}/${def.name}`,
    kind: 'export',
    saved: 'export',
    label: def.name,
    to: `/exports/${encodeURIComponent(def.schema_name)}/${encodeURIComponent(def.name)}`,
    context: def.schema_name,
  }
}

/** A drilled-down place in the explorer: whatever the address bar holds. */
export function placeTarget(to: string, label: string, context?: string) {
  return {
    key: targetKeys.place(to),
    kind: 'place',
    label,
    to,
    context,
  } satisfies NavTarget
}
