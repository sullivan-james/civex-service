import { useMemo, useRef, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import {
  schemasApi,
  type FromFilenamePreview,
  type FromFilenameResult,
} from '../../api/schemas'
import { useDebouncedValue } from '../../hooks/useDebouncedValue'
import {
  captureForDateFormat,
  choiceSpan,
  dateFormats,
  describeDateFormat,
  hasNumberInside,
  keyClashes,
  looksLike,
  nameParts,
  placePattern,
  textBefore,
  textPattern,
  type PartChoice,
} from '../../utils/patternFromExample'
import { normalizeNumericKey } from '../../utils/filenamePattern'
import { DATE_KINDS } from '../../utils/filenameExtract'
import {
  Button,
  CheckRow,
  Chip,
  DataTable,
  Disclosure,
  Field,
  FileDropZone,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  SegmentedControl,
  Select,
  Textarea,
  type DataTableColumn,
} from '../ui'

/** What the dialog gives back: the pattern, and for a date read in two steps
 * (`civex.value_from_filename`), the date format beside it. */
export interface PatternChoice {
  pattern: string
  dateFormat?: string
}

/** The most names the server is asked about at once. */
const MAX_NAMES = 500

/** What a pattern makes of each of the names, the server's answer (asked
 * once the pattern stops changing). */
function useNamesPreview(pattern: string, names: string[], kind: string) {
  const asked = useDebouncedValue(
    { pattern, names: names.slice(0, MAX_NAMES) },
    300,
  )
  return useQuery({
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
}

/** How many names a pattern gives a value for that looks like the one
 * picked in `example`. */
function fitOf(data: FromFilenamePreview | undefined, example: string): number {
  if (!data || data.problems.some(Boolean)) return -1
  const results = data.results ?? []
  const picked = results.find((r) => r.filename === example)?.value
  if (picked === null || picked === undefined) return -1
  return results.filter(
    (r) =>
      r.value !== null &&
      r.value !== undefined &&
      !r.error &&
      looksLike(String(r.value), String(picked)),
  ).length
}

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
  const [choice, setChoice] = useState<PartChoice | null>(null)
  const [byChosen, setBy] = useState<'place' | 'text' | null>(null)
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
    setChoice(null)
    setFormat('')
  }

  const parts = useMemo(() => nameParts(example), [example])
  // A chip's click carries no event, so Shift is read as it goes down.
  const shift = useRef(false)
  // Click a part; Shift+click another to take everything between.
  function pick(index: number, extend: boolean) {
    setWritten(null)
    setFormat('')
    if (extend && choice) {
      setChoice({
        from: Math.min(choice.from, index),
        to: Math.max(choice.to, index),
        digitsOnly: false,
      })
      return
    }
    const one = { from: index, to: index, digitsOnly: false }
    // A part that is mostly a label and a number ("dive07") usually means the number.
    setChoice({ ...one, digitsOnly: !isDate && hasNumberInside(parts, one) })
  }

  const span = choice ? choiceSpan(parts, choice) : null
  const markedText = span ? example.slice(span.start, span.end) : ''
  const formats = useMemo(
    () =>
      span && isDate
        ? dateFormats(
            example,
            span.start,
            span.end,
            kind === 'date' ? 'date' : 'datetime',
          )
        : [],
    [span?.start, span?.end, isDate, example, kind], // eslint-disable-line react-hooks/exhaustive-deps
  )
  const chosenFormat = formats.includes(format) ? format : (formats[0] ?? '')
  const byPlace = choice && !isDate ? placePattern(choice, parts) : ''
  const byText = choice && !isDate ? textPattern(example, parts, choice) : null
  const before = choice ? textBefore(example, parts, choice) : null
  const placeTry = useNamesPreview(byPlace, names, kind)
  const textTry = useNamesPreview(byText ?? '', names, kind)
  // Whichever gives more names a value like the one picked, unless the
  // person said.
  const by: 'place' | 'text' =
    byChosen ??
    (byText && fitOf(textTry.data, example) > fitOf(placeTry.data, example)
      ? 'text'
      : 'place')
  const generated = choice
    ? isDate
      ? chosenFormat
      : by === 'text' && byText
        ? byText
        : byPlace
    : ''
  const pattern = written ?? generated

  const preview = useNamesPreview(pattern, names, kind)
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
                    ? 'Click the date in the name'
                    : 'Click the part of the name you want'
                }
                info="Shift+click another part to take everything between. The other names are read the same way."
              >
                <div className="flex flex-wrap items-center gap-1 font-mono text-sm">
                  {parts.map((part, i) => {
                    const on = !!choice && i >= choice.from && i <= choice.to
                    const sep = example.slice(
                      part.end,
                      parts[i + 1]?.start ?? part.end,
                    )
                    return (
                      <span
                        key={i}
                        className="flex items-center gap-1"
                        onClickCapture={(e) => {
                          shift.current = e.shiftKey
                        }}
                      >
                        <Chip
                          selected={on}
                          onClick={() => pick(i, shift.current)}
                          aria-pressed={on}
                        >
                          {part.text}
                        </Chip>
                        {sep && <span className="text-fg-muted">{sep}</span>}
                      </span>
                    )
                  })}
                </div>
              </Field>
              {choice && hasNumberInside(parts, choice) && !isDate && (
                <CheckRow
                  compact
                  title={`Just the number in it (${parts[choice.from].text.match(/[0-9]+/)?.[0]})`}
                  checked={choice.digitsOnly}
                  onChange={(on) => setChoice({ ...choice, digitsOnly: on })}
                />
              )}
              {choice && !isDate && byText && (
                <Field label="Find it by">
                  <SegmentedControl
                    label="Find it by"
                    value={by}
                    onChange={(v) => setBy(v)}
                    options={[
                      {
                        value: 'place',
                        label: `Its place: part ${choice.from + 1}`,
                      },
                      {
                        value: 'text',
                        label: `What comes before it: “${before}”`,
                      },
                    ]}
                  />
                </Field>
              )}
              {choice && isDate && formats.length === 0 && (
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
