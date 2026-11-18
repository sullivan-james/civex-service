import { useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { schemasApi, type FromFilenameResult } from '../../api/schemas'
import { useDebouncedValue } from '../../hooks/useDebouncedValue'
import {
  captureForDateFormat,
  dateFormats,
  describeDateFormat,
  keyClashes,
  keyPattern,
} from '../../utils/patternFromExample'
import { normalizeNumericKey } from '../../utils/filenamePattern'
import { DATE_KINDS } from '../../utils/filenameExtract'
import {
  Button,
  DataTable,
  Disclosure,
  Field,
  FileDropZone,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Select,
  Textarea,
  type DataTableColumn,
} from '../ui'

/** What the dialog gives back: the pattern, and for a date read in two steps
 * (`civex.extract_from_filename`), the date format beside it. */
export interface PatternChoice {
  pattern: string
  dateFormat?: string
}

/** The most names the server is asked about at once. */
const MAX_NAMES = 500

interface Row {
  filename: string
  result: FromFilenameResult | undefined
  clashesWith: string[]
}

/**
 * Build a file-name pattern by marking the part of an example name that is
 * wanted, then see what it makes of every name before using it. The server
 * reads the names (`POST /schemas/from-filename/preview`), so what is shown
 * is what a run or a save will do.
 *
 * `dateStyle`: a date is given back as `{pattern: <capture>, dateFormat:
 * <token format>}` (`separate`, the workflow action) or as `{pattern: <token
 * format>}` (`token`, a field's from-file-name rule). `initialPattern` is the
 * pattern as it is tried on names: for a `separate` date, the date format.
 */
export function PatternFromExampleDialog({
  kind,
  examples,
  dateStyle,
  checkClashes = false,
  initialPattern,
  onApply,
  onClose,
}: {
  kind: string
  examples: string[]
  dateStyle: 'separate' | 'token'
  checkClashes?: boolean
  initialPattern?: string
  onApply: (choice: PatternChoice) => void
  onClose: () => void
}) {
  const isDate = DATE_KINDS.has(kind)
  const [names, setNames] = useState<string[]>(() => [...new Set(examples)])
  const [example, setExample] = useState(names[0] ?? '')
  const [marked, setMarked] = useState<{ start: number; end: number } | null>(
    null,
  )
  const [format, setFormat] = useState('')
  // What the person typed in "Write the pattern yourself", if anything.
  const [written, setWritten] = useState<string | null>(initialPattern || null)
  const [pasted, setPasted] = useState('')

  function addNames(more: string[]) {
    const next = [
      ...new Set([...names, ...more.map((n) => n.trim()).filter(Boolean)]),
    ]
    setNames(next)
    if (!example && next.length) setExample(next[0])
  }

  function chooseExample(name: string) {
    setExample(name)
    setMarked(null)
    setFormat('')
  }

  const markedText = marked ? example.slice(marked.start, marked.end) : ''
  const formats = useMemo(
    () =>
      marked && isDate
        ? dateFormats(
            example,
            marked.start,
            marked.end,
            kind === 'date' ? 'date' : 'datetime',
          )
        : [],
    [marked, isDate, example, kind],
  )
  const chosenFormat = formats.includes(format) ? format : (formats[0] ?? '')
  const generated = marked
    ? isDate
      ? chosenFormat
      : keyPattern(example, marked.start, marked.end)
    : ''
  const pattern = written ?? generated

  const asked = useDebouncedValue(
    { pattern, names: names.slice(0, MAX_NAMES) },
    300,
  )
  const preview = useQuery({
    queryKey: ['from-filename-preview', 'many', kind, asked],
    queryFn: () =>
      schemasApi.previewFromFilename({
        filename: '',
        patterns: [asked.pattern],
        kind,
        filenames: asked.names,
      }),
    enabled: !!asked.pattern && asked.names.length > 0,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  })
  const problem = pattern ? (preview.data?.problems[0] ?? null) : null
  const results = useMemo(
    () => (problem ? [] : (preview.data?.results ?? [])),
    [problem, preview.data],
  )
  const byName = useMemo(
    () => new Map(results.map((r) => [r.filename, r])),
    [results],
  )
  const clashes = useMemo(
    () => (checkClashes ? keyClashes(results) : new Map<string, string[]>()),
    [checkClashes, results],
  )
  const rows: Row[] = names.map((filename) => {
    const result = byName.get(filename)
    const key =
      result && result.value !== null && result.value !== undefined
        ? normalizeNumericKey(String(result.value))
        : null
    const together = key !== null ? (clashes.get(key) ?? []) : []
    return {
      filename,
      result,
      clashesWith: together.filter((n) => n !== filename),
    }
  })
  const giving = results.filter((r) => r.value !== null && !r.error).length
  const clashing = [...clashes.values()].reduce((n, v) => n + v.length, 0)
  const tried = results.length > 0

  function apply() {
    if (!pattern) return
    if (isDate && dateStyle === 'separate') {
      onApply({ pattern: captureForDateFormat(pattern), dateFormat: pattern })
    } else {
      onApply({ pattern })
    }
  }

  const columns: DataTableColumn<Row>[] = [
    {
      key: 'filename',
      header: 'File name',
      render: (row) => (
        <span className="font-mono text-xs">{row.filename}</span>
      ),
    },
    {
      key: 'gives',
      header: 'Gives',
      render: (row) => <Gives row={row} />,
    },
  ]

  return (
    <Modal onClose={onClose} size="xl">
      <ModalHeader>Build from an example</ModalHeader>
      <ModalBody>
        <div className="space-y-4">
          {names.length === 0 ? (
            <p className="text-sm text-fg-muted">
              Add a file name or two to work from.
            </p>
          ) : (
            <>
              {names.length > 1 && (
                <Field label="Example">
                  <Select
                    size="sm"
                    value={example}
                    onChange={(e) => chooseExample(e.target.value)}
                  >
                    {names.map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
              <Field
                label={
                  isDate
                    ? 'Select the date in the name'
                    : 'Select the part of the name you want'
                }
                info="Drag across it with the mouse, or hold Shift and use the arrow keys. Other names written the same way are read alike."
              >
                {/* Not readOnly: browsers don't move the caret in a read-only
                    box, so Shift+arrows couldn't select. Typing changes
                    nothing, since the value is the example's. */}
                <Input
                  value={example}
                  onChange={() => undefined}
                  aria-readonly
                  spellCheck={false}
                  aria-label="Example file name"
                  className="font-mono"
                  onSelect={(e) => {
                    const el = e.currentTarget
                    const start = el.selectionStart ?? 0
                    const end = el.selectionEnd ?? 0
                    if (end > start) {
                      setMarked({ start, end })
                      setWritten(null)
                    }
                  }}
                />
              </Field>
              {marked && (
                <p className="text-sm" data-testid="marked">
                  Marked: <span className="font-mono">{markedText}</span>
                </p>
              )}
              {marked && isDate && formats.length === 0 && (
                <p role="alert" className="text-sm text-danger">
                  That doesn't read as a date. Select the whole date, for
                  example 20240611 or 2024-06-11_142233.
                </p>
              )}
              {formats.length > 1 && (
                <Field label="It reads as">
                  <Select
                    size="sm"
                    value={chosenFormat}
                    onChange={(e) => {
                      setFormat(e.target.value)
                      setWritten(null)
                    }}
                  >
                    {formats.map((f) => (
                      <option key={f} value={f}>
                        {describeDateFormat(markedText, f)}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
              {formats.length === 1 && (
                <p className="text-sm">
                  Reads as {describeDateFormat(markedText, formats[0])}.
                </p>
              )}
            </>
          )}

          {problem && (
            <p role="alert" className="text-sm text-danger">
              The pattern can't be used: {problem}.
            </p>
          )}
          {tried && (
            <p role="status" className="text-sm" data-testid="summary">
              {giving} of {names.length} names give a value
              {clashing > 0 && (
                <span className="text-danger">
                  ; {clashing} give the same key as another
                </span>
              )}
              .
            </p>
          )}
          {names.length > 0 && (
            <DataTable
              columns={columns}
              rows={rows}
              getRowId={(r) => r.filename}
              maxHeight="16rem"
              dense
              rowClassName={(r) =>
                r.clashesWith.length > 0 ? 'bg-danger-subtle' : ''
              }
            />
          )}

          <Disclosure summary="Add more file names">
            <div className="space-y-3 p-3">
              <FileDropZone
                multiple
                onFiles={(files) => addNames(files.map((f) => f.name))}
                inputLabel="Choose files to add their names"
              >
                Choose files to add their names. Nothing is uploaded.
              </FileDropZone>
              <Field label="Or paste names, one per line">
                <Textarea
                  size="sm"
                  rows={3}
                  value={pasted}
                  onChange={(e) => setPasted(e.target.value)}
                />
              </Field>
              <Button
                size="sm"
                disabled={!pasted.trim()}
                onClick={() => {
                  addNames(pasted.split('\n'))
                  setPasted('')
                }}
              >
                Add these names
              </Button>
            </div>
          </Disclosure>

          <Disclosure summary="Write the pattern yourself">
            <div className="p-3">
              <Field
                label="Pattern"
                info={
                  isDate
                    ? 'Tokens YYYY MM DD HH mm SS; anything else is a regular expression, so [-_] takes a dash or an underscore.'
                    : 'A regular expression. The part in brackets ( ) is the value.'
                }
              >
                <Input
                  size="sm"
                  value={pattern}
                  className="font-mono"
                  onChange={(e) => setWritten(e.target.value)}
                />
              </Field>
            </div>
          </Disclosure>
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="primary"
          onClick={apply}
          disabled={!pattern || !!problem}
        >
          Use this pattern
        </Button>
      </ModalFooter>
    </Modal>
  )
}

function Gives({ row }: { row: Row }) {
  const { result, clashesWith } = row
  if (!result) return <span className="text-fg-subtle">…</span>
  if (result.error)
    return <span className="text-danger">Matches, but {result.error}</span>
  if (result.value === null || result.value === undefined)
    return <span className="text-fg-subtle">Doesn't match</span>
  return (
    <span className={clashesWith.length ? 'text-danger' : ''}>
      <span className="font-mono">{String(result.value)}</span>
      {clashesWith.length > 0 && (
        <> — the same key as {clashesWith.join(', ')}</>
      )}
    </span>
  )
}
