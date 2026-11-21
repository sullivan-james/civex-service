import type { RecordSelectionBody } from '../../api/records'
import type { Schema } from '../../api/schemas'
import { useAddToAnalytics } from '../../hooks/useDashboard'
import { usePermissions } from '../../hooks/useMe'
import { Button, IconButton, Subheading } from '../ui'
import { BarChart3, Maximize2, PanelRightClose } from '../ui/icons'
import { ChartBoard } from '../charts/ChartBoard'
import type { FilterTreeWire } from '../../utils/filterTree'
import type { ExplorerCharts } from './useExplorerCharts'

/** The charts beside a list: the kind's chart cards. Every chart counts
 * exactly the records listed and a click on a bar filters them. A change is
 * saved for the kind at once. */
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
  onExpand,
  onCollapse,
  onBack,
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
  /** Show the charts alone, at full width (absent when they already are). */
  onExpand?: () => void
  /** Fold the panel away to its strip. */
  onCollapse?: () => void
  /** At full width: the way back to the records. */
  onBack?: () => void
}) {
  const { canSomewhere } = usePermissions()
  const addToAnalytics = useAddToAnalytics()
  const mayAdd = canSomewhere('write_records')
  return (
    <section aria-label="Charts" className="space-y-3">
      {/* Level with the records' heading beside it. */}
      <div className="flex min-h-9 flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <Subheading as="h2">Charts</Subheading>
          {onBack && (
            <Button size="sm" variant="link" onClick={onBack}>
              Back to records
            </Button>
          )}
        </div>
        {/* The panel's own controls, as the navigation's on the left. */}
        <div className="flex items-center">
          {onExpand && (
            <IconButton
              icon={Maximize2}
              size="sm"
              aria-label="Charts at full width"
              onClick={onExpand}
            />
          )}
          {onCollapse && (
            <IconButton
              icon={PanelRightClose}
              size="sm"
              aria-label="Collapse charts"
              onClick={onCollapse}
            />
          )}
        </div>
      </div>
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
          // One way to add at a time: not while the builder is open.
          onBuild={
            model.building || model.editing || !mayAdd ? undefined : model.build
          }
          // Shared like a saved filter: whoever may write records may.
          onChange={mayAdd ? model.set : undefined}
          onFilter={onFilter}
          onOpen={model.setOpen}
          onEdit={model.edit}
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
