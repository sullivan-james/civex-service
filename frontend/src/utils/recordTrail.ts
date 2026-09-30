import type { BreadcrumbItem } from '../components/ui/Page'
import { displayLabel } from './naming'

/** Collections › the collection › each record on the way down, root first.
 * Shared by every page about a record (or a record-to-be) so they all read
 * the same; the page adds its own final crumb. */
export function recordTrail(
  collection: { name: string; id: string } | undefined,
  path: {
    id: string
    natural_name: string | null
    schema_name: string
  }[] = [],
  /** Display name for a schema; the name, prettified, when absent. */
  schemaLabel: (name: string) => string = (n) => displayLabel(n, null),
): BreadcrumbItem[] {
  return [
    { label: 'Collections', to: '/collections' },
    ...(collection
      ? [{ label: collection.name, to: `/collections/${collection.id}` }]
      : []),
    ...path.map((r) => ({
      label: r.natural_name ?? r.id.slice(0, 8),
      to: `/records/${r.id}`,
      kind: schemaLabel(r.schema_name),
    })),
  ]
}
