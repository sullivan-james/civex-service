import { useState } from 'react'
import { Field } from './Field'
import { Input } from './Input'
import { nameError, slugify } from '../../utils/naming'

export interface NameLabelValue {
  label: string
  name: string
}

export interface NameLabelFieldsProps {
  value: NameLabelValue
  onChange: (next: NameLabelValue) => void
  kind: 'Schema' | 'Field'
  /**
   * Derive the name from the label as the user types. On for creation, off
   * for editing: an existing name is what workflows reference, so it is
   * never rewritten behind the user's back.
   */
  deriveName?: boolean
  autoFocus?: boolean
  onEnter?: () => void
}

/**
 * The label/name pair, in that order.
 *
 * Label comes first because it is the one people actually think in; the name
 * fills itself in from it and most users never touch it. Once they do edit
 * the name by hand, deriving stops — otherwise the next keystroke in the
 * label would silently overwrite their choice.
 */
export function NameLabelFields({
  value,
  onChange,
  kind,
  deriveName = true,
  autoFocus = false,
  onEnter,
}: NameLabelFieldsProps) {
  const [derive, setDerive] = useState(deriveName)
  const error = value.name ? nameError(value.name) : null

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && onEnter) onEnter()
  }

  return (
    <>
      <Field label={`${kind} label`} span={4}>
        <Input
          size="sm"
          value={value.label}
          onChange={(e) =>
            onChange({
              label: e.target.value,
              name: derive ? slugify(e.target.value) : value.name,
            })
          }
          onKeyDown={handleKeyDown}
          placeholder={
            kind === 'Field' ? 'Recording Date' : 'Acoustic Recording'
          }
          autoFocus={autoFocus}
        />
      </Field>
      <Field
        label={`${kind} name`}
        span={4}
        error={error}
        hint="Used by workflows and CSV headers."
      >
        <Input
          size="sm"
          className="font-mono"
          value={value.name}
          onChange={(e) => {
            setDerive(false)
            onChange({ label: value.label, name: e.target.value })
          }}
          onKeyDown={handleKeyDown}
          placeholder={
            kind === 'Field' ? 'recording_date' : 'acoustic_recording'
          }
        />
      </Field>
    </>
  )
}
