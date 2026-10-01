import { useState } from 'react'
import { Button, IconButton, Input } from '../ui'
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
      <div className="max-h-64 overflow-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-canvas-subtle text-left text-xs text-fg-muted">
            <tr>
              <th className="px-2 py-1 font-medium">#</th>
              <th className="px-2 py-1 font-medium">Latitude</th>
              <th className="px-2 py-1 font-medium">Longitude</th>
              <th className="px-2 py-1" />
            </tr>
          </thead>
          <tbody>
            {rows.map(([lon, lat], i) => (
              <tr key={i} className="border-t border-border-muted">
                <td className="px-2 py-1 text-xs text-fg-subtle tabular-nums">
                  {i + 1}
                </td>
                <td className="px-1 py-0.5">
                  <Input
                    size="sm"
                    defaultValue={lat}
                    key={`lat-${i}-${lat}`}
                    aria-label={`${noun} ${i + 1} latitude`}
                    inputMode="decimal"
                    onBlur={(e) => set(i, 1, e.target.value)}
                    className="w-36 font-mono"
                  />
                </td>
                <td className="px-1 py-0.5">
                  <Input
                    size="sm"
                    defaultValue={lon}
                    key={`lon-${i}-${lon}`}
                    aria-label={`${noun} ${i + 1} longitude`}
                    inputMode="decimal"
                    onBlur={(e) => set(i, 0, e.target.value)}
                    className="w-36 font-mono"
                  />
                </td>
                <td className="whitespace-nowrap px-1 text-right">
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
                    onClick={() =>
                      onChange(positions.filter((_, j) => j !== i))
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {positions.length > SHOWN && !showAll && (
        <p className="text-xs text-fg-muted">
          Showing the first {SHOWN} of {positions.length.toLocaleString()}{' '}
          {noun}s.{' '}
          <button
            type="button"
            className="text-accent hover:underline cursor-pointer"
            onClick={() => setShowAll(true)}
          >
            Show all
          </button>
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
