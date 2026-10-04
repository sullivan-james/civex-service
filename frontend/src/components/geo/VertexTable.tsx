import { useState } from 'react'
import { Button, DataTable, IconButton, Input } from '../ui'
import { ChevronDown, ChevronUp, X } from '../ui/icons'
import type { Position } from '../../utils/geoDraft'

const SHOWN = 200

/** The points of a line or area as editable rows. Long tracks are shown in
 * part: the map is the way to reshape those. */
export function VertexTable({
  positions,
  noun,
  onChange,
}: {
  positions: Position[]
  /** "point" or "corner". */
  noun: string
  onChange: (next: Position[]) => void
}) {
  const [showAll, setShowAll] = useState(false)
  const rows = showAll ? positions : positions.slice(0, SHOWN)
  const set = (i: number, axis: 0 | 1, raw: string) => {
    const n = Number(raw)
    if (raw.trim() === '' || Number.isNaN(n)) return
    const limit = axis === 0 ? 180 : 90
    if (Math.abs(n) > limit) return
    onChange(
      positions.map((p, j) =>
        j === i ? (axis === 0 ? [n, p[1]] : [p[0], n]) : p,
      ),
    )
  }
  const move = (i: number, by: -1 | 1) => {
    const j = i + by
    if (j < 0 || j >= positions.length) return
    const next = [...positions]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }
  return (
    <div className="space-y-2">
      <DataTable
        layout="auto"
        maxHeight="16rem"
        columns={[
          {
            key: 'n',
            header: '#',
            width: '3rem',
            className: 'text-fg-subtle tabular-nums',
            render: (r: { i: number }) => r.i + 1,
          },
          {
            key: 'lat',
            header: 'Latitude',
            render: ({ i }) => (
              <Input
                size="sm"
                defaultValue={positions[i][1]}
                key={`lat-${i}-${positions[i][1]}`}
                aria-label={`${noun} ${i + 1} latitude`}
                inputMode="decimal"
                onBlur={(e) => set(i, 1, e.target.value)}
                className="w-36 font-mono"
              />
            ),
          },
          {
            key: 'lon',
            header: 'Longitude',
            render: ({ i }) => (
              <Input
                size="sm"
                defaultValue={positions[i][0]}
                key={`lon-${i}-${positions[i][0]}`}
                aria-label={`${noun} ${i + 1} longitude`}
                inputMode="decimal"
                onBlur={(e) => set(i, 0, e.target.value)}
                className="w-36 font-mono"
              />
            ),
          },
        ]}
        rows={rows.map((_, i) => ({ i }))}
        getRowId={({ i }) => String(i)}
        actionsWidth="7.5rem"
        actions={({ i }) => (
          <>
            <IconButton
              icon={ChevronUp}
              aria-label={`Move ${noun} ${i + 1} up`}
              variant="subtle"
              disabled={i === 0}
              onClick={() => move(i, -1)}
            />
            <IconButton
              icon={ChevronDown}
              aria-label={`Move ${noun} ${i + 1} down`}
              variant="subtle"
              disabled={i === positions.length - 1}
              onClick={() => move(i, 1)}
            />
            <IconButton
              icon={X}
              aria-label={`Remove ${noun} ${i + 1}`}
              variant="subtle"
              onClick={() => onChange(positions.filter((_, j) => j !== i))}
            />
          </>
        )}
      />
      {positions.length > SHOWN && !showAll && (
        <p className="text-xs text-fg-muted">
          Showing the first {SHOWN} of {positions.length.toLocaleString()}{' '}
          {noun}s.{' '}
          <Button size="sm" variant="link" onClick={() => setShowAll(true)}>
            Show all
          </Button>
        </p>
      )}
      <Button
        size="sm"
        onClick={() => {
          const last = positions[positions.length - 1] ?? [0, 0]
          onChange([...positions, [last[0], last[1]]])
        }}
      >
        + Add {noun}
      </Button>
    </div>
  )
}
