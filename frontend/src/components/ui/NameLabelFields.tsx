import { useState } from 'react'
import { Button } from './Button'
import { InfoTip } from './Tooltip'
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
  // The name is for workflows and CSV headers; most people never need to
  // see it, so while it follows the label it is one line with a way in.
  const [showName, setShowName] = useState(!deriveName)
  const error = value.name ? nameError(value.name) : null

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && onEnter) onEnter()
  }

  return (
    <>
      <Field
        label="Name"
        span={6}
        info={`What the ${kind.toLowerCase()} is called everywhere in the app.`}
      >
        <Input
          value={value.label}
          onChange={(e) =>
            onChange({
              label: e.target.value,
              name: derive ? slugify(e.target.value) : value.name,
            })
          }
          onKeyDown={handleKeyDown}
          placeholder={kind === 'Field' ? 'Visited On' : 'Soil Sample'}
          autoFocus={autoFocus}
        />
      </Field>
      {showName || error ? (
        <Field
          label="Key"
          span={6}
          error={error}
          info="The identifier workflows, CSV headers and the API use. Changing it means updating workflows that use it."
        >
          <Input
            className="font-mono"
            value={value.name}
            onChange={(e) => {
              setDerive(false)
              onChange({ label: value.label, name: e.target.value })
            }}
            onKeyDown={handleKeyDown}
            placeholder={kind === 'Field' ? 'visited_on' : 'soil_sample'}
          />
        </Field>
      ) : (
        <p className="col-span-full flex items-center gap-1 text-xs text-fg-subtle">
          Key <span className="font-mono">{value.name || '…'}</span>
          <InfoTip>
            The identifier workflows, CSV headers and the API use. It follows
            the name until you change it.
          </InfoTip>
          <Button
            variant="link"
            size="sm"
            className="text-xs"
            onClick={() => setShowName(true)}
          >
            change
          </Button>
        </p>
      )}
    </>
  )
}
