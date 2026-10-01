import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { Field } from '../../api/schemas'
import { Button, Checkbox, Popover, Td } from '../ui'
import { DynamicField } from './DynamicField'
import { FieldValue } from './FieldValue'
import { coerceFieldValue, sameValue } from '../../utils/recordValues'
import { displayLabel } from '../../utils/naming'
import { errorMessage } from '../../lib/errors'

/** Types whose editor is too big (or has its own dropdown) to sit inside a
 * table cell: they edit in a `Popover` instead. Everything else edits in
 * place. Both use the same `DynamicField`, so restriction-aware behaviour
 * (choices, min/max, accept/max_size, ...) isn't reimplemented here. */
const POPOVER_TYPES = new Set([
  'file',
  'file_list',
  'reference',
  'reference_list',
])

interface EditableCellProps {
  field: Field
  value: unknown
  referenceLabels?: Record<string, string | null> | null
  referenceCollections?: Record<string, string> | null
  /** Persist the new (already coerced; `undefined` = cleared) value. Reject
   * to keep the cell in edit mode with the error shown. The caller decides
   * what "persist" means -- a PATCH for an existing row, or just local state
   * for a not-yet-created draft row. */
  onCommit: (value: unknown) => Promise<void> | void
  /** Names the row in the accessible label, e.g. the record's name. */
  rowLabel?: string
  disabled?: boolean
}

/** A table cell that edits like a spreadsheet / a rename in a file manager:
 * click (or focus + Enter/F2) to edit, Enter or clicking away to save, Esc
 * to cancel. Booleans toggle directly. File and reference fields open a
 * popover with Save/Cancel. */
export function EditableCell({
  field,
  value,
  referenceLabels,
  referenceCollections,
  onCommit,
  rowLabel,
  disabled = false,
}: EditableCellProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<unknown>(value)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  // State (not a ref) so the Popover gets the element during render.
  const [cell, setCell] = useState<HTMLTableCellElement | null>(null)
  const editorRef = useRef<HTMLDivElement>(null)
  // Set once a commit/cancel has started, so the blur that follows the
  // editor unmounting doesn't commit a second time.
  const finishedRef = useRef(false)
  // Only pull focus back to the cell after a *keyboard* finish -- after a
  // click-away the user's focus belongs to whatever they clicked.
  const refocusRef = useRef(false)
  const wasEditingRef = useRef(false)

  const label = displayLabel(field.name, field.label)
  const inPopover = POPOVER_TYPES.has(field.type)
  const cellLabel = rowLabel ? `${label}, ${rowLabel}` : label

  useEffect(() => {
    if (wasEditingRef.current && !editing && refocusRef.current) {
      cell?.focus()
    }
    wasEditingRef.current = editing
    refocusRef.current = false
  }, [editing, cell])

  // Inline editors take focus as soon as they mount.
  useEffect(() => {
    if (!editing || inPopover) return
    editorRef.current
      ?.querySelector<HTMLElement>('input, select, textarea')
      ?.focus()
  }, [editing, inPopover])

  function open() {
    if (disabled || editing) return
    finishedRef.current = false
    setDraft(value)
    setError(null)
    setEditing(true)
  }

  function cancel(refocus = false) {
    finishedRef.current = true
    refocusRef.current = refocus
    setEditing(false)
    setError(null)
  }

  async function commit(next: unknown, refocus = false) {
    const coerced = coerceFieldValue(next, field.type)
    if (sameValue(coerced, value)) {
      cancel(refocus)
      return
    }
    finishedRef.current = true
    setSaving(true)
    setError(null)
    try {
      await onCommit(coerced)
      refocusRef.current = refocus
      setEditing(false)
    } catch (err) {
      // Stay open with the draft intact so the value can be fixed.
      finishedRef.current = false
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  function handleCellKeyDown(e: KeyboardEvent<HTMLTableCellElement>) {
    if (e.target !== e.currentTarget) return
    if (e.key === 'Enter' || e.key === 'F2') {
      e.preventDefault()
      open()
    }
  }

  function handleEditorKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      void commit(draft, true)
    } else if (e.key === 'Escape') {
      e.stopPropagation()
      cancel(true)
    }
  }

  if (field.type === 'boolean') {
    return (
      <Td>
        <Checkbox
          checked={value === true}
          disabled={disabled || saving}
          aria-label={cellLabel}
          aria-invalid={!!error}
          onChange={(e) => {
            void commit(e.target.checked)
          }}
        />
        {error && <p className="mt-1 text-xs text-danger">{error}</p>}
      </Td>
    )
  }

  const showInline = editing && !inPopover

  return (
    <Td
      ref={setCell}
      tabIndex={showInline || disabled ? undefined : 0}
      aria-label={showInline ? undefined : `Edit ${cellLabel}`}
      onClick={(e) => {
        // Links / buttons inside the value (references, downloads) keep
        // their own behaviour.
        if ((e.target as HTMLElement).closest('a, button, input')) return
        open()
      }}
      onKeyDown={showInline ? undefined : handleCellKeyDown}
      className={
        disabled
          ? ''
          : 'cursor-text hover:bg-accent-subtle focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent'
      }
    >
      {showInline ? (
        <div
          ref={editorRef}
          onKeyDown={handleEditorKeyDown}
          onBlur={(e) => {
            if (finishedRef.current) return
            if (e.currentTarget.contains(e.relatedTarget as Node | null)) return
            void commit(draft)
          }}
        >
          <DynamicField
            field={field}
            value={draft}
            onChange={setDraft}
            aria-invalid={!!error}
          />
          {error && (
            <p role="alert" className="mt-1 text-xs text-danger">
              {error}
            </p>
          )}
        </div>
      ) : (
        <FieldValue
          value={value}
          field={field}
          referenceLabels={referenceLabels}
          referenceCollections={referenceCollections}
        />
      )}

      {editing && inPopover && (
        <Popover
          anchor={cell}
          label={`Edit ${cellLabel}`}
          onClose={() => cancel()}
        >
          <div className="space-y-3 min-w-[16rem]">
            <DynamicField
              field={field}
              value={draft}
              onChange={setDraft}
              aria-invalid={!!error}
            />
            {error && (
              <p role="alert" className="text-xs text-danger">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button size="sm" onClick={() => cancel()}>
                Cancel
              </Button>
              <Button
                size="sm"
                variant="primary"
                disabled={saving}
                onClick={() => void commit(draft)}
              >
                {saving ? 'Saving…' : 'Save'}
              </Button>
            </div>
          </div>
        </Popover>
      )}
    </Td>
  )
}
