import { Button } from '../ui'
import type { CivexRecord } from '../../api/records'
import { pluralise } from '../../lib/utils'
import { displayLabel } from '../../utils/naming'

/** One button per child schema a row has records of -- "3 recordings →" --
 * that lists them in the same explorer, scoped to that row. Shared by the explorer's
 * table and the record page's preview of what it contains. */
export function DrillLinks({
  counts,
  byName,
  onDrill,
}: {
  counts: CivexRecord['child_counts']
  byName: Map<string, { name: string; label: string | null }>
  onDrill: (childSchema: string) => void
}) {
  const entries = Object.entries(counts ?? {})
  if (entries.length === 0) return <span className="text-fg-subtle">—</span>
  return (
    <span className="flex flex-wrap gap-1">
      {entries.map(([name, n]) => {
        const s = byName.get(name)
        return (
          <Button
            key={name}
            size="sm"
            variant="link"
            onClick={() => onDrill(name)}
          >
            {pluralise(n, displayLabel(name, s?.label).toLowerCase())} →
          </Button>
        )
      })}
    </span>
  )
}
