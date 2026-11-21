import { useState } from 'react'
import type { RecordSelectionBody } from '../../api/records'
import type { Chart, Schema } from '../../api/schemas'
import { Button, Card, IconButton, Menu, type MenuEntry } from '../ui'
import { GripVertical, MoreVertical, Plus } from '../ui/icons'
import { chartTitle, type Usable } from '../../utils/charts'
import type { FilterTreeWire } from '../../utils/filterTree'
import { ChartView } from './ChartView'

export interface ChartBoardProps {
  charts: Chart[]
  /** The records every chart counts. */
  records: RecordSelectionBody
  usable: Usable[]
  /** The kind's display name ("Sample"). */
  kind: string
  schemas: Schema[]
  /** Start building a chart (the host shows `NewChart` at full width). */
  onBuild?: () => void
  /** The charts may change: add, remove, reorder. */
  onChange?: (charts: Chart[]) => void
  /** Bars filter the records listed (`ChartView`). */
  onFilter?: (filter: FilterTreeWire | null) => void
  /** Show a chart with its numbers (`OpenChart`). */
  onOpen?: (chart: Chart) => void
  /** Change a chart (the host opens the builder on it). */
  onEdit?: (chart: Chart) => void
  /** More to do with a chart, in its menu (Add to Analytics page). */
  more?: (chart: Chart, title: string) => MenuEntry[]
  enabled?: boolean
}

/** Chart cards: the one board behind a kind's Charts tab and the
 * explorer's charts column. A card's menu shows its numbers and, where the
 * charts may change, edits it, makes it larger or smaller, moves or removes
 * it; and **Add chart** asks the
 * host to open the builder (`NewChart`, at full width).
 * Cards flow into as many columns as the width holds. */
export function ChartBoard({
  charts,
  records,
  usable,
  kind,
  schemas,
  onBuild,
  onChange,
  onFilter,
  onOpen,
  onEdit,
  more,
  enabled = true,
}: ChartBoardProps) {
  const fields = usable.map((u) => u.field)
  // The card being dragged, and the one it is over.
  const [dragged, setDragged] = useState<number | null>(null)
  const [over, setOver] = useState<number | null>(null)
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
        const large = chart.size === 'large'
        const items: MenuEntry[] = [
          ...(onChange && onEdit
            ? [{ label: 'Edit…', onClick: () => onEdit(chart) }]
            : []),
          ...(onChange
            ? [
                {
                  label: large ? 'Smaller' : 'Larger',
                  onClick: () =>
                    onChange(
                      charts.map((c) =>
                        c.id === chart.id
                          ? { ...c, size: large ? 'small' : 'large' }
                          : c,
                      ),
                    ),
                },
              ]
            : []),
          // Not a bigger chart (that is Larger): the chart with its table of
          // numbers and their download.
          ...(onOpen
            ? [{ label: 'See numbers', onClick: () => onOpen(chart) }]
            : []),
          ...(more?.(chart, title) ?? []),
          ...(onChange && i > 0
            ? [{ label: 'Move up', onClick: () => move(i, i - 1) }]
            : []),
          ...(onChange && i < charts.length - 1
            ? [{ label: 'Move down', onClick: () => move(i, i + 1) }]
            : []),
          ...(onChange
            ? [
                {
                  label: 'Remove',
                  variant: 'danger' as const,
                  onClick: () =>
                    onChange(charts.filter((c) => c.id !== chart.id)),
                },
              ]
            : []),
        ]
        return (
          <div
            key={chart.id}
            // A large chart takes the whole width of the board. Where the
            // charts may change, a card is dragged by its title to its place.
            className={`${large ? 'col-span-full' : ''} ${
              over === i && dragged !== null && dragged !== i
                ? 'rounded-lg outline-2 outline-accent'
                : ''
            }`}
            onDragOver={
              onChange
                ? (e) => {
                    if (dragged === null) return
                    e.preventDefault()
                    setOver(i)
                  }
                : undefined
            }
            onDrop={
              onChange
                ? (e) => {
                    e.preventDefault()
                    if (dragged !== null && dragged !== i) move(dragged, i)
                    setDragged(null)
                    setOver(null)
                  }
                : undefined
            }
          >
            <Card
              title={
                <span
                  className={`flex items-center gap-1 text-sm ${onChange ? 'cursor-grab' : ''}`}
                  draggable={!!onChange}
                  onDragStart={(e) => {
                    e.dataTransfer.effectAllowed = 'move'
                    setDragged(i)
                  }}
                  onDragEnd={() => {
                    setDragged(null)
                    setOver(null)
                  }}
                >
                  {onChange && (
                    <GripVertical
                      size={14}
                      className="shrink-0 text-fg-subtle"
                      aria-hidden="true"
                    />
                  )}
                  {title}
                </span>
              }
              action={
                <div className="flex items-center">
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
          </div>
        )
      })}
      {onChange && onBuild && (
        <Button className="min-h-16 border-dashed" onClick={onBuild}>
          <Plus size={14} /> Add chart
        </Button>
      )}
    </div>
  )
}

/** A chart with its numbers: at full width, beside its table, with the
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
