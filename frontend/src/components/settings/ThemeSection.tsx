import { useEffect, useState } from 'react'
import { Field, SegmentedControl, Select } from '../ui'
import { useTheme, type ThemePreference } from '../../hooks/useTheme'
import {
  setUiSize,
  UI_SIZES,
  useUiSize,
  type UiSize,
} from '../../hooks/useUiSize'
import { setDateFormat, useDateFormat } from '../../hooks/useDateFormat'
import {
  DATE_FORMATS,
  formatInstantDate,
  formatTime,
  type DateFormat,
} from '../../utils/dates'

const options: { value: ThemePreference; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

const sizeOptions = UI_SIZES.map((size) => ({
  value: String(size),
  label: `${size}%`,
}))

/** The current minute, kept fresh so the example reads as now. */
function useNow(): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

export default function ThemeSection() {
  const { preference, setPreference } = useTheme()
  const size = useUiSize()
  const dateFormat = useDateFormat()
  const now = useNow()
  // Minutes only: the example is about the date, not a ticking clock.
  const minute = new Date(now)
  minute.setSeconds(0, 0)

  return (
    <div className="space-y-5">
      <SegmentedControl
        label="Theme"
        options={options}
        value={preference}
        onChange={setPreference}
      />
      <SegmentedControl
        label="Size"
        options={sizeOptions}
        value={String(size)}
        onChange={(next) => setUiSize(Number(next) as UiSize)}
      />
      <div className="space-y-1">
        <Field
          label="Date format"
          info="How dates are shown and typed in this browser. Exports and files keep YYYY-MM-DD."
        >
          <Select
            value={dateFormat}
            onChange={(e) => setDateFormat(e.target.value as DateFormat)}
            className="w-56"
          >
            {DATE_FORMATS.map((format) => (
              <option key={format} value={format}>
                {format}
              </option>
            ))}
          </Select>
        </Field>
        <p className="text-sm text-fg-muted">
          Today: {formatInstantDate(minute)} {formatTime(minute)}
        </p>
      </div>
    </div>
  )
}
