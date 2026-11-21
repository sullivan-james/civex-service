import type { RecordSummary } from '../../api/records'
import { Button, Card, Subheading } from '../ui'
import { displayLabel } from '../../utils/naming'
import type { FilterConditionWire } from '../../utils/filterTree'
import type { RailLevel } from './HierarchyRail'
import { SummaryChart } from './SummaryChart'

/** Beside a list of every kind: how many records of each kind are here,
 * drawn by the charts' own renderer. A bar lists that kind. */
export function KindsChart({
  levels,
  total,
  onPick,
  onHide,
}: {
  levels: RailLevel[]
  total: number
  onPick: (schema: string) => void
  onHide: () => void
}) {
  const counted = levels.filter((l) => l.count !== null)
  const summary: RecordSummary = {
    schema_name: '',
    group_columns: [
      {
        key: '@kind',
        field: '@kind',
        schema_name: '',
        label: 'Kind',
        type: 'string',
        bucket: null,
        bin: null,
        unit: null,
      },
    ],
    measure_columns: [
      {
        key: 'count',
        measure: 'count',
        label: 'Records',
        field: null,
        schema_name: null,
        type: null,
        unit: null,
      },
    ],
    rows: counted.map((l) => ({
      groups: [
        {
          value: l.schema.name,
          label: displayLabel(l.schema.name, l.schema.label),
          lower: null,
          upper: null,
          precision: null,
        },
      ],
      values: [l.count],
      where: { field: '@kind', op: 'eq', value: l.schema.name },
    })),
    total: [total],
    truncated: false,
    limit: counted.length,
    timezone: null,
  }
  return (
    <section aria-label="Charts" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Subheading as="h2">Charts</Subheading>
        <Button size="sm" variant="ghost" onClick={onHide}>
          Hide charts
        </Button>
      </div>
      <Card title={<span className="text-sm">How many of each kind</span>}>
        <div>
          <SummaryChart
            summary={summary}
            measureKey={null}
            compact
            onDrill={(where) =>
              onPick(String((where as FilterConditionWire).value))
            }
          />
        </div>
      </Card>
    </section>
  )
}
