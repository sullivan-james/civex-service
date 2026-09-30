import { useMemo } from 'react'
import { Select, type SelectProps } from './Select'
import { timeZoneOptions } from '../../utils/timeZones'

interface TimeZoneSelectProps extends Omit<
  SelectProps,
  'value' | 'onChange' | 'children'
> {
  /** An IANA zone, or '' for "not set". */
  value: string
  onChange: (value: string) => void
  /** Text for the empty option, e.g. "Not set — each viewer's own timezone". */
  unsetLabel: string
}

/** Picker for an IANA timezone with an explicit "not set" choice. */
export function TimeZoneSelect({
  value,
  onChange,
  unsetLabel,
  ...props
}: TimeZoneSelectProps) {
  const options = useMemo(() => timeZoneOptions(value), [value])
  return (
    <Select value={value} onChange={(e) => onChange(e.target.value)} {...props}>
      <option value="">{unsetLabel}</option>
      {options.map((tz) => (
        <option key={tz} value={tz}>
          {tz}
        </option>
      ))}
    </Select>
  )
}
