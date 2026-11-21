import { useState } from 'react'
import type { RecordSelectionBody } from '../../api/records'
import type { Chart, Schema } from '../../api/schemas'
import { Button, Card, IconButton, Menu, type MenuEntry } from '../ui'
import { MoreVertical, Plus, X } from '../ui/icons'
import { chartTitle, type Usable } from '../../utils/charts'
import type { FilterTreeWire } from '../../utils/filterTree'
import { ChartView } from './ChartView'
import { NewChart } from './NewChart'

export interface ChartBoardProps {
  charts: Chart[]
  /** The records every chart counts. */
  records: RecordSelectionBody
  usable: Usable[]
  /** The kind's display name ("Sample"). */
  kind: string
  schemas: Schema[]
  /** The kind listed: with `onChange`, charts can be added. */
  listed?: Schema
  /** The charts may change: add, remove, reorder. */
  onChange?: (charts: Chart[]) => void
  /** Bars filter the records listed (`ChartView`). */
  onFilter?: (filter: FilterTreeWire | null) => void
  /** Open a chart large. */
  onOpen?: (chart: Chart) => void
  /** More to do with a chart, in its menu (Add to Analytics page). */
  more?: (chart: Chart, title: string) => MenuEntry[]
  enabled?: boolean
}

/** Chart cards: the one board behind a kind's Charts tab and the
 * explorer's charts column. Each card can be opened large; where the charts
 * may change, a card can be moved or removed and **Add chart** makes one.
 * Cards flow into as many columns as the width holds. */
export function ChartBoard({
  charts,
  records,
  usable,
  kind,
  schemas,
  listed,
  onChange,
  onFilter,
  onOpen,
  more,
  enabled = true,
}: ChartBoardProps) {
  const [adding, setAdding] = useState(false)
  const fields = usable.map((u) => u.field)
  const move = (from: number, to: number) => {
    const next = [...charts]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    onChange?.(next)
  }
  return (
    <div
      className="grid items-start gap-3"
      style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(16rem, 1fr))' }}
    >
      {charts.map((chart, i) => {
        const title = chartTitle(chart, usable, kind, schemas)
        const items: MenuEntry[] = [
          ...(more?.(chart, title) ?? []),
          ...(onChange && i > 0
            ? [{ label: 'Move up', onClick: () => move(i, i - 1) }]
            : []),
          ...(onChange && i < charts.length - 1
            ? [{ label: 'Move down', onClick: () => move(i, i + 1) }]
            : []),
        ]
        return (
          <Card
            key={chart.id}
            title={<span className="text-sm">{title}</span>}
            action={
              <div className="flex items-center">
                {onOpen && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onOpen(chart)}
                  >
                    Open
                  </Button>
                )}
                {items.length > 0 && (
                  <Menu
                    items={items}
                    trigger={({ open, toggle }) => (
                      <IconButton
                        icon={MoreVertical}
                        size="sm"
                        variant="subtle"
                        aria-label={`More for ${title}`}
                        aria-haspopup="menu"
                        aria-expanded={open}
                        onClick={toggle}
                      />
                    )}
                  />
                )}
                {onChange && (
                  <IconButton
                    icon={X}
                    size="sm"
                    variant="subtle"
                    aria-label={`Remove ${title}`}
                    onClick={() =>
                      onChange(charts.filter((c) => c.id !== chart.id))
                    }
                  />
                )}
              </div>
            }
          >
            <div>
              <ChartView
                chart={chart}
                records={records}
                fields={fields}
                onFilter={onFilter}
                enabled={enabled}
              />
            </div>
          </Card>
        )
      })}
      {onChange &&
        listed &&
        (adding ? (
          <NewChart
            listed={listed}
            schemas={schemas}
            usable={usable}
            kind={kind}
            onAdd={(chart) => {
              onChange([...charts, chart])
              setAdding(false)
            }}
            onCancel={() => setAdding(false)}
          />
        ) : (
          <Button
            className="min-h-16 border-dashed"
            onClick={() => setAdding(true)}
          >
            <Plus size={14} /> Add chart
          </Button>
        ))}
    </div>
  )
}

/** A chart opened large: full width, with its table of numbers, the
 * download and **Close**. Bars still filter where `onFilter` is given. */
export function OpenChart({
  chart,
  title,
  records,
  usable,
  onFilter,
  onClose,
}: {
  chart: Chart
  title: string
  records: RecordSelectionBody
  usable: Usable[]
  onFilter?: (filter: FilterTreeWire | null) => void
  onClose: () => void
}) {
  return (
    <Card
      title={title}
      selected
      action={
        <Button size="sm" onClick={onClose}>
          Close
        </Button>
      }
    >
      <div>
        <ChartView
          chart={chart}
          records={records}
          fields={usable.map((u) => u.field)}
          onFilter={onFilter}
          large
        />
      </div>
    </Card>
  )
}
