import type { RecordSelectionBody } from '../../api/records'
import type { Schema } from '../../api/schemas'
import { useAddToAnalytics } from '../../hooks/useDashboard'
import { usePermissions } from '../../hooks/useMe'
import { Button, Subheading } from '../ui'
import { BarChart3 } from '../ui/icons'
import { ChartBoard } from '../charts/ChartBoard'
import type { FilterTreeWire } from '../../utils/filterTree'
import type { ExplorerCharts } from './useExplorerCharts'

/** The charts beside a list: the chart cards, and
 * while they differ from the kind's own, **Use for every Sample list** and
 * **Put back**. Every chart counts exactly the records listed and a click on
 * a bar filters them. */
export function ChartsColumn({
  model,
  listed,
  schemas,
  kind,
  records,
  scope,
  onFilter,
  enabled,
  onShow,
}: {
  model: ExplorerCharts
  listed: Schema
  schemas: Schema[]
  /** The kind's display name ("Sample"). */
  kind: string
  records: RecordSelectionBody
  /** Where the records are, by id, for a card on the Analytics page. */
  scope: { collection: string | null; within: string | null }
  onFilter: (filter: FilterTreeWire | null) => void
  /** False: the list is too big to chart without being asked. */
  enabled: boolean
  onShow: () => void
}) {
  const { can, canSomewhere, why } = usePermissions()
  const addToAnalytics = useAddToAnalytics()
  const mayAdd = canSomewhere('write_records')
  return (
    <section aria-label="Charts" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Subheading as="h2">Charts</Subheading>
      </div>
      {model.changed && (
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={!can('change_structure') || model.saving}
            title={
              can('change_structure') ? undefined : why('change_structure')
            }
            onClick={model.saveForKind}
          >
            Use for every {kind} list
          </Button>
          <Button size="sm" variant="ghost" onClick={model.putBack}>
            Put back
          </Button>
        </div>
      )}
      {!enabled ? (
        <Button size="sm" onClick={onShow}>
          <BarChart3 size={14} /> Show charts
        </Button>
      ) : (
        <ChartBoard
          charts={model.charts}
          records={records}
          usable={model.usable}
          kind={kind}
          schemas={schemas}
          listed={listed}
          onChange={model.set}
          onFilter={onFilter}
          onOpen={model.setOpen}
          more={(chart, title) => [
            {
              label: 'Add to Analytics page',
              disabled: !mayAdd,
              onClick: () =>
                addToAnalytics.mutate({
                  chart,
                  title,
                  records: {
                    schema: listed.id,
                    collection: scope.collection,
                    within: scope.within,
                    search: records.search,
                    filter: records.filter as FilterTreeWire | null,
                  },
                }),
            },
          ]}
        />
      )}
    </section>
  )
}
