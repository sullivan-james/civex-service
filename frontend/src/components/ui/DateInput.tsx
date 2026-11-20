import { useRef, useState } from 'react'
import { Input } from './Input'
import { IconButton } from './IconButton'
import { CalendarDays } from './icons'
import type { ControlSize } from './controlStyles'
import { useDateFormat } from '../../hooks/useDateFormat'
import {
  datePlaceholder,
  formatDate,
  formatWallTime,
  isWallTime,
  parseDateAtLeast,
  parseWallTime,
  type DateFormat,
} from '../../utils/dates'
import type { Precision } from '../../utils/partialDates'

interface Shared {
  id?: string
  value: string
  /** The stored form when the text reads as one, '' when it is empty, and
   * the text as typed when it doesn't (so a form or the server can refuse
   * it rather than something else being kept). */
  onChange: (value: string) => void
  /** Bounds for the calendar, in the stored form. */
  min?: string
  max?: string
  required?: boolean
  disabled?: boolean
  placeholder?: string
  /** Shown on hover over the text box. */
  title?: string
  size?: ControlSize
  className?: string
  /** The caller says what is wrong itself (the input still turns red). */
  hideError?: boolean
  'aria-label'?: string
  'aria-describedby'?: string
  'aria-invalid'?: boolean
}

/** Opens the browser's own calendar for a hidden native input, so a date can
 * be picked, while what is shown and typed follows the chosen pattern. */
function openPicker(input: HTMLInputElement | null) {
  if (!input) return
  try {
    input.showPicker()
  } catch {
    input.focus()
    input.click()
  }
}

/** A text box in the chosen pattern with a calendar button (the one way the
 * app takes a date). Text is kept as typed while it changes; a value set from
 * outside (or another pattern) is shown afresh. */
function PatternInput({
  id,
  value,
  onChange,
  min,
  max,
  required,
  disabled,
  placeholder,
  title,
  size = 'md',
  className = '',
  hideError,
  'aria-label': ariaLabel,
  'aria-describedby': ariaDescribedby,
  'aria-invalid': ariaInvalid,
  show,
  read,
  pickerType,
  pickerValue,
  example,
  label,
}: Shared & {
  show: (value: string, format: DateFormat) => string
  read: (text: string, format: DateFormat) => string | null
  pickerType: 'date' | 'datetime-local'
  pickerValue: (value: string) => string
  example: string
  label: string
}) {
  const format = useDateFormat()
  // `source` is the value the text stands for, `seen` the last `value`
  // given. A new `value` that reads differently from the text is from
  // outside and replaces it; one that reads the same (a caller's round trip
  // dropping `:00` seconds) leaves the typing be, and so does a caller that
  // ignores text it can't use (the value doesn't change).
  const [state, setState] = useState(() => ({
    text: show(value, format),
    source: value,
    seen: value,
    format,
  }))
  let text = state.text
  if (state.format !== format) {
    text = show(value, format)
    setState({ text, source: value, seen: value, format })
  } else if (state.seen !== value) {
    if (show(state.source, format) !== show(value, format))
      text = show(value, format)
    setState({ text, source: value, seen: value, format })
  }
  const picker = useRef<HTMLInputElement>(null)

  function emit(nextText: string, next: string) {
    setState((st) => ({ ...st, text: nextText, source: next }))
    onChange(next)
  }

  function typed(nextText: string) {
    const trimmed = nextText.trim()
    emit(nextText, trimmed === '' ? '' : (read(trimmed, format) ?? nextText))
  }

  const bad = text.trim() !== '' && read(text.trim(), format) === null
  const small = size === 'sm'
  return (
    <div className={className}>
      {/* The button sits on the box, not on the box plus a message below. */}
      <div className="relative">
        <Input
          id={id}
          size={size}
          value={text}
          disabled={disabled}
          required={required}
          aria-required={required || undefined}
          aria-label={ariaLabel}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid || bad || undefined}
          invalid={bad}
          placeholder={placeholder ?? example}
          title={title}
          onChange={(e) => typed(e.target.value)}
          className={`w-full ${small ? 'pr-8' : 'pr-10'}`}
        />
        <input
          ref={picker}
          type={pickerType}
          step={pickerType === 'datetime-local' ? 1 : undefined}
          tabIndex={-1}
          aria-hidden
          min={min}
          max={max}
          value={pickerValue(value)}
          onChange={(e) => {
            if (!e.target.value) return
            emit(show(e.target.value, format), e.target.value)
          }}
          className="pointer-events-none absolute bottom-0 right-0 h-px w-px opacity-0"
        />
        <span
          className={`absolute top-1/2 -translate-y-1/2 ${small ? 'right-1' : 'right-0.5'}`}
        >
          <IconButton
            icon={CalendarDays}
            aria-label={label}
            size={small ? 'xs' : 'sm'}
            disabled={disabled}
            onClick={() => openPicker(picker.current)}
          />
        </span>
      </div>
      {bad && !hideError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          Not a date. Use {example}.
        </p>
      )}
    </div>
  )
}

/** A calendar date typed in the chosen pattern (Settings → Appearance), with
 * a button for the browser's calendar. `value` and `onChange` use the stored
 * form: `2019-06-14`, or `2019-06` / `2019` where `precision` (the least
 * precise form allowed, default a day) lets a month or a year stand. */
export function DateInput({
  precision = 'day',
  ...props
}: Shared & { precision?: Precision }) {
  const format = useDateFormat()
  const fullDay = (v: string) => (/^\d{4}-\d{2}-\d{2}$/.test(v) ? v : '')
  return (
    <PatternInput
      {...props}
      min={props.min && fullDay(props.min)}
      max={props.max && fullDay(props.max)}
      show={(v, f) => formatDate(v, f)}
      read={(t, f) => parseDateAtLeast(t, precision, f)}
      pickerType="date"
      pickerValue={fullDay}
      example={datePlaceholder(precision, format)}
      label="Pick a date"
    />
  )
}

/** A date and 24-hour time typed as `<date in the chosen pattern> HH:MM`
 * (seconds optional), with a button for the browser's calendar. `value` and
 * `onChange` are wall time as `<input type="datetime-local">` gives it
 * (`2024-03-01T15:30[:45]`): a drop-in for that input, so a caller converts
 * to and from UTC as before (`utcToZonedLocal`, `datetimeInputToWire`). */
export function DateTimeInput(props: Shared) {
  const format = useDateFormat()
  return (
    <PatternInput
      {...props}
      show={(v, f) => formatWallTime(v, f) || v}
      read={(t, f) => parseWallTime(t, f)}
      pickerType="datetime-local"
      pickerValue={(v) => (isWallTime(v) ? v : '')}
      example={`${datePlaceholder('day', format)} HH:MM`}
      label="Pick a date and time"
    />
  )
}
