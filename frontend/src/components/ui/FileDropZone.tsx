import { useState, type DragEvent, type ReactNode } from 'react'

/** The one way to choose files: a dashed zone you can drop onto or click, with
 * a real file input inside it so keyboards and screen readers work, and a
 * `<label for>` elsewhere can name it. Used for attaching files to a record and
 * for a workflow's file inputs, so they look and behave alike. It only reports
 * the files chosen; what happens to them (upload now, or keep until Run) is the
 * caller's business, as is checking them against `accept` and a size limit. */
export function FileDropZone({
  onFiles,
  multiple = false,
  accept,
  disabled = false,
  id,
  inputLabel,
  children,
  'aria-describedby': describedBy,
  'aria-invalid': invalid,
  required,
}: {
  onFiles: (files: File[]) => void
  multiple?: boolean
  /** Hint for the browser's picker; dropped files are not filtered by it. */
  accept?: string
  disabled?: boolean
  id?: string
  /** Accessible name of the file input, when no `<label for>` names it. */
  inputLabel?: string
  /** What to say inside the zone, instead of the default prompt. */
  children?: ReactNode
  'aria-describedby'?: string
  'aria-invalid'?: boolean
  required?: boolean
}) {
  const [over, setOver] = useState(false)

  function drop(e: DragEvent) {
    e.preventDefault()
    setOver(false)
    if (disabled) return
    const files = Array.from(e.dataTransfer.files)
    if (files.length) onFiles(multiple ? files : files.slice(0, 1))
  }

  return (
    <label
      onDragOver={(e) => {
        e.preventDefault()
        e.dataTransfer.dropEffect = 'copy'
        if (!disabled) setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
      className={`relative flex min-h-12 items-center justify-center rounded-md border-2 border-dashed px-4 py-3 text-center text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent ${
        disabled
          ? 'cursor-not-allowed border-border text-fg-subtle opacity-60'
          : over
            ? 'cursor-pointer border-accent bg-accent-subtle text-fg'
            : 'cursor-pointer border-border text-fg-muted hover:border-accent hover:bg-canvas-subtle'
      }`}
    >
      <input
        id={id}
        type="file"
        multiple={multiple}
        accept={accept}
        disabled={disabled}
        required={required}
        aria-required={required}
        aria-label={inputLabel}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        className="sr-only"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          e.target.value = ''
          if (files.length) onFiles(files)
        }}
      />
      {children ?? (
        <span>
          Drop {multiple ? 'files' : 'a file'} here or{' '}
          <span className="text-accent">browse</span>
        </span>
      )}
    </label>
  )
}
