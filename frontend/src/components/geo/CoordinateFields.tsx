import { useState } from 'react'
import { Input, Select } from '../ui'
import {
  fromDms,
  parseCoordinates,
  toDms,
  type CoordFormat,
} from '../../utils/geoCoords'

type Axis = 'lat' | 'lon'
const LIMIT: Record<Axis, number> = { lat: 90, lon: 180 }
const HEMI: Record<Axis, [string, string]> = {
  lat: ['N', 'S'],
  lon: ['E', 'W'],
}
const NAME: Record<Axis, string> = { lat: 'Latitude', lon: 'Longitude' }

const fmt = (n: number, places: number) => String(parseFloat(n.toFixed(places)))

/** Boxes for one axis in the chosen format, always as magnitude plus a
 * hemisphere so nobody has to remember that west is negative. */
function parts(value: number | null, format: CoordFormat): string[] {
  if (value === null)
    return format === 'dd' ? [''] : format === 'ddm' ? ['', ''] : ['', '', '']
  const abs = Math.abs(value)
  if (format === 'dd') return [fmt(abs, 7)]
  const d = toDms(abs)
  if (format === 'ddm')
    return [String(d.degrees), fmt(d.minutes + d.seconds / 60, 5)]
  return [String(d.degrees), String(d.minutes), fmt(d.seconds, 3)]
}

function AxisInput({
  axis,
  value,
  format,
  onChange,
}: {
  axis: Axis
  value: number | null
  format: CoordFormat
  onChange: (v: number | null) => void
}) {
  const [text, setText] = useState(() => parts(value, format))
  const [south, setSouth] = useState(value !== null && value < 0)
  // The value we last reported. When `value` differs, it changed somewhere
  // else (the map, the paste box): take it over.
  const [emitted, setEmitted] = useState<number | null>(value)
  if (value !== emitted) {
    setEmitted(value)
    setText(parts(value, format))
    if (value !== null) setSouth(value < 0)
  }

  const filled = text.filter((t) => t.trim() !== '')
  const nums = text.map((t) => (t.trim() === '' ? 0 : Number(t)))
  let error: string | null = null
  if (filled.length > 0) {
    if (text.some((t) => t.trim() !== '' && Number.isNaN(Number(t))))
      error = 'Numbers only.'
    else if (nums.some((n) => n < 0))
      error = 'Enter it without a sign; use the hemisphere box.'
    else if (format !== 'dd' && (nums[1] >= 60 || (nums[2] ?? 0) >= 60))
      error = 'Minutes and seconds are under 60.'
    else {
      const mag =
        format === 'dd'
          ? nums[0]
          : format === 'ddm'
            ? nums[0] + nums[1] / 60
            : fromDms({
                negative: false,
                degrees: nums[0],
                minutes: nums[1],
                seconds: nums[2],
              })
      if (mag > LIMIT[axis]) error = `${NAME[axis]} is at most ${LIMIT[axis]}°.`
    }
  }

  function update(i: number | null, v: string, hemisouth?: boolean) {
    const t = i === null ? text : text.map((x, j) => (j === i ? v : x))
    const s = hemisouth ?? south
    setText(t)
    setSouth(s)
    const f = t.filter((x) => x.trim() !== '')
    let n: number | null = null
    const ns = t.map((x) => (x.trim() === '' ? 0 : Number(x)))
    if (f.length && !ns.some((x) => Number.isNaN(x) || x < 0)) {
      const mag =
        format === 'dd'
          ? ns[0]
          : format === 'ddm'
            ? ns[0] + ns[1] / 60
            : fromDms({
                negative: false,
                degrees: ns[0],
                minutes: ns[1],
                seconds: ns[2],
              })
      const ok =
        mag <= LIMIT[axis] &&
        (format === 'dd' || (ns[1] < 60 && (ns[2] ?? 0) < 60))
      n = ok ? (s ? -mag : mag) : null
      if (!ok) return
    }
    setEmitted(n)
    onChange(n)
  }

  const units =
    format === 'dd' ? ['°'] : format === 'ddm' ? ['°', '′'] : ['°', '′', '″']
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="w-20 shrink-0 text-xs font-medium text-fg-muted">
          {NAME[axis]}
        </span>
        {units.map((u, i) => (
          <span key={u} className="flex items-center gap-1">
            <Input
              size="sm"
              inputMode="decimal"
              value={text[i]}
              aria-label={`${NAME[axis]} ${['degrees', 'minutes', 'seconds'][i]}`}
              aria-invalid={!!error}
              placeholder={['0', '0', '0'][i]}
              onChange={(e) => update(i, e.target.value)}
              className={format === 'dd' ? 'w-32' : i === 0 ? 'w-16' : 'w-20'}
            />
            <span className="text-fg-muted">{u}</span>
          </span>
        ))}
        <Select
          size="sm"
          value={south ? HEMI[axis][1] : HEMI[axis][0]}
          aria-label={`${NAME[axis]} hemisphere`}
          onChange={(e) => update(null, '', e.target.value === HEMI[axis][1])}
          className="w-16"
        >
          <option>{HEMI[axis][0]}</option>
          <option>{HEMI[axis][1]}</option>
        </Select>
      </div>
      {error && (
        <p role="alert" className="pl-[5.5rem] text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  )
}

/** Latitude and longitude boxes, plus a paste box that understands the
 * formats people copy from maps, GPS units and field notebooks. */
export function CoordinateFields({
  lat,
  lon,
  format,
  onChange,
}: {
  lat: number | null
  lon: number | null
  format: CoordFormat
  onChange: (lat: number | null, lon: number | null) => void
}) {
  const [paste, setPaste] = useState('')
  const parsed = paste.trim() ? parseCoordinates(paste) : null
  const bad =
    paste.trim() !== '' &&
    (parsed === null || Math.abs(parsed[0]) > 90 || Math.abs(parsed[1]) > 180)
  return (
    <div className="space-y-3">
      <AxisInput
        key={`lat-${format}`}
        axis="lat"
        value={lat}
        format={format}
        onChange={(v) => onChange(v, lon)}
      />
      <AxisInput
        key={`lon-${format}`}
        axis="lon"
        value={lon}
        format={format}
        onChange={(v) => onChange(lat, v)}
      />
      <div className="space-y-1">
        <label
          className="block text-xs font-medium text-fg-muted"
          htmlFor="paste-coords"
        >
          Or paste coordinates
        </label>
        <Input
          id="paste-coords"
          size="sm"
          value={paste}
          aria-invalid={bad}
          placeholder={`56°07'12"N 3°24'36"W   or   56.12, -3.41`}
          onChange={(e) => {
            setPaste(e.target.value)
            const p = parseCoordinates(e.target.value)
            if (p && Math.abs(p[0]) <= 90 && Math.abs(p[1]) <= 180) {
              onChange(p[0], p[1])
            }
          }}
          onBlur={() => !bad && setPaste('')}
          className="max-w-md font-mono"
        />
        {bad && (
          <p role="alert" className="text-xs text-danger">
            Couldn't read that. Try 56.12, -3.41 or 56°07′12″N 3°24′36″W.
          </p>
        )}
      </div>
    </div>
  )
}
