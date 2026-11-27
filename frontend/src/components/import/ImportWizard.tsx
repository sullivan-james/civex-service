import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { auditApi } from '../../api/audit'
import { importsApi, type ImportSheet } from '../../api/imports'
import { useSchemas } from '../../hooks/useSchemas'
import { errorMessage } from '../../lib/errors'
import { Button, FormError, ProgressBar, Stepper } from '../ui'
import { ColumnsStep } from './ColumnsStep'
import { FileStep } from './FileStep'
import { ReviewStep } from './ReviewStep'
import {
  NO_TOTALS,
  buildRequest,
  nameFromFile,
  runInParts,
  suggestMatch,
  suggestSettings,
  summary,
  whyNot,
  type Choices,
  type ColumnSetting,
  type Target,
  type Totals,
} from './importPlan'

const STEPS = [
  { label: 'File' },
  { label: 'Columns' },
  { label: 'Check' },
  { label: 'Import' },
]

type Phase = 'file' | 'columns' | 'check' | 'import' | 'done'

/** Bringing a spreadsheet in, one full page at a time: choose the file, say
 * where each column goes, see what will happen (and which rows won't work), then
 * import. Nothing is kept until the last step, which goes through the file a
 * part at a time and says how far it has got. */
export function ImportWizard({
  collection,
  collectionId,
  collections,
  initialKind,
  recordsHref,
}: {
  /** The collection the records go in, by name and id; none to choose one
   * (or make one) in the wizard, from `collections`. */
  collection?: string
  collectionId?: string
  collections?: string[]
  /** The kind of record the list was showing, if any. */
  initialKind?: string | null
  /** Where "See the records" goes. */
  recordsHref: (kind: string, collection: string) => string
}) {
  const { data: schemas } = useSchemas()
  const queryClient = useQueryClient()
  const topLevel = useMemo(
    () => (schemas ?? []).filter((s) => !s.parent_id && !s.deleted_at),
    [schemas],
  )
  const [phase, setPhase] = useState<Phase>('file')
  const [file, setFile] = useState<{ sha256: string; filename: string } | null>(
    null,
  )
  const [sheet, setSheet] = useState<ImportSheet | null>(null)
  const [target, setTarget] = useState<Target>({ kind: 'new', label: '' })
  const [settings, setSettings] = useState<ColumnSetting[]>([])
  const [match, setMatch] = useState('')
  const [place, setPlace] = useState<{ name: string; isNew: boolean }>({
    name: collection ?? '',
    isNew: false,
  })
  const [ifExists, setIfExists] = useState<Choices['ifExists']>('update')
  const [checked, setChecked] = useState<Totals | null>(null)
  const [checking, setChecking] = useState<{ next: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<{
    totals: Totals
    next: number
    batch: string | null
  } | null>(null)
  const [saving, setSaving] = useState<{ totals: Totals; next: number } | null>(
    null,
  )
  const abort = useRef<AbortController | null>(null)
  useEffect(() => () => abort.current?.abort(), [])

  const schema =
    target.kind === 'existing'
      ? topLevel.find((s) => s.name === target.name)
      : undefined
  const choices: Choices | null =
    file && sheet
      ? {
          filename: file.filename,
          sha256: file.sha256,
          sheet,
          target,
          schema,
          collection: place.name,
          newCollection: place.isNew,
          settings,
          match,
          ifExists,
          kinds: (schemas ?? []).map((s) => s.name),
        }
      : null

  function startFrom(read: ImportSheet, name: string, sha256: string) {
    setFile({ sha256, filename: name })
    // Chosen here: a new collection named from the file, unless one is picked.
    if (!collection) setPlace({ name: nameFromFile(name), isNew: true })
    setSheet(read)
    const first = topLevel.find((s) => s.name === initialKind)
    const next: Target = first
      ? { kind: 'existing', name: first.name }
      : { kind: 'new', label: nameFromFile(name) }
    setTarget(next)
    const s = suggestSettings(read.columns, first)
    setSettings(s)
    setMatch(suggestMatch(s, first))
    setIfExists('update')
    setPhase('columns')
  }

  function pickTarget(next: Target) {
    if (!sheet) return
    setTarget(next)
    const s = suggestSettings(
      sheet.columns,
      next.kind === 'existing'
        ? topLevel.find((k) => k.name === next.name)
        : undefined,
    )
    setSettings(s)
    setMatch(
      suggestMatch(
        s,
        next.kind === 'existing'
          ? topLevel.find((k) => k.name === next.name)
          : undefined,
      ),
    )
  }

  async function pickSheet(name: string) {
    if (!file) return
    setError(null)
    try {
      const read = await importsApi.inspect(file.sha256, file.filename, name)
      setSheet(read)
      const s = suggestSettings(read.columns, schema)
      setSettings(s)
      setMatch(suggestMatch(s, schema))
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function check() {
    if (!choices) return
    setPhase('check')
    setError(null)
    setChecked(null)
    setChecking({ next: 0 })
    abort.current?.abort()
    const controller = new AbortController()
    abort.current = controller
    const request = buildRequest(choices)
    const result = await runInParts(
      (start, limit) => importsApi.run(request, start, limit, true),
      sheet!.total,
      (_t, next) => setChecking({ next }),
      { signal: controller.signal },
    )
    if (result.cancelled) return
    setChecking(null)
    if (result.error) setError(errorMessage(result.error))
    else setChecked(result.totals)
  }

  async function save(resume?: {
    totals: Totals
    next: number
    batch: string
  }) {
    if (!choices) return
    setPhase('import')
    setError(null)
    abort.current?.abort()
    const controller = new AbortController()
    abort.current = controller
    const request = buildRequest(choices)
    let batch: string | null = resume?.batch ?? null
    try {
      if (!batch)
        batch = (await auditApi.openBatch('import', file!.filename)).id
    } catch (e) {
      setError(errorMessage(e))
      return
    }
    setSaving({ totals: resume?.totals ?? NO_TOTALS, next: resume?.next ?? 0 })
    const id = batch
    const result = await runInParts(
      (start, limit) => importsApi.run(request, start, limit, false, id),
      sheet!.total,
      (totals, next) => setSaving({ totals, next }),
      {
        signal: controller.signal,
        from: resume?.next,
        totals: resume?.totals,
      },
    )
    if (result.cancelled) return
    if (result.error) {
      setError(errorMessage(result.error))
      setSaving({ totals: result.totals, next: result.next })
      setDone({ totals: result.totals, next: result.next, batch: id })
      return
    }
    setDone({ totals: result.totals, next: result.next, batch: id })
    setSaving(null)
    setPhase('done')
    // What was brought in changes lists, counts and the kinds there are.
    void queryClient.invalidateQueries()
  }

  const active =
    phase === 'file' ? 0 : phase === 'columns' ? 1 : phase === 'check' ? 2 : 3
  const kind = choices ? buildRequest(choices).kind : ''

  return (
    <div className="max-w-5xl space-y-6">
      <Stepper steps={STEPS} activeIndex={phase === 'done' ? 4 : active} />

      {phase === 'file' && (
        <FileStep collectionId={collectionId} onRead={startFrom} />
      )}

      {phase === 'columns' && choices && (
        <ColumnsStep
          choices={choices}
          topLevel={topLevel}
          onTarget={pickTarget}
          places={collection ? undefined : (collections ?? [])}
          place={place}
          onPlace={setPlace}
          onSheet={pickSheet}
          onSettings={setSettings}
          onMatch={setMatch}
          onIfExists={setIfExists}
          problem={whyNot(choices)}
          error={error}
          onBack={() => {
            setError(null)
            setPhase('file')
          }}
          onNext={() => void check()}
        />
      )}

      {phase === 'check' && choices && (
        <ReviewStep
          choices={choices}
          checking={checking}
          totals={checked}
          error={error}
          onBack={() => {
            abort.current?.abort()
            setPhase('columns')
          }}
          onImport={() => void save()}
        />
      )}

      {phase === 'import' && (
        <div className="space-y-3">
          <h2 className="text-base font-semibold text-fg">Importing</h2>
          <ProgressBar
            label="Rows imported"
            className="w-full max-w-xl"
            fraction={
              sheet && sheet.total > 0 ? (saving?.next ?? 0) / sheet.total : 0
            }
          />
          <p className="text-sm text-fg-muted">
            {(saving?.next ?? 0).toLocaleString()} of{' '}
            {(sheet?.total ?? 0).toLocaleString()} rows
          </p>
          <FormError message={error} />
          {error && done && (
            <div className="flex gap-2">
              <Button
                variant="primary"
                onClick={() =>
                  void save({
                    totals: done.totals,
                    next: done.next,
                    batch: done.batch!,
                  })
                }
              >
                Try again
              </Button>
              <p className="self-center text-sm text-fg-muted">
                Rows before {done.next.toLocaleString()} are already in.
              </p>
            </div>
          )}
        </div>
      )}

      {phase === 'done' && done && (
        <div className="space-y-4">
          <h2 className="text-base font-semibold text-fg">Done</h2>
          <p className="text-sm text-fg">{summary(done.totals)}</p>
          {done.totals.skipped > 0 && (
            <p className="text-sm text-fg-muted">
              {done.totals.skipped.toLocaleString()} rows were not saved; the
              check showed why.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Link
              to={recordsHref(kind, place.name.trim())}
              className="inline-flex items-center rounded-md bg-accent px-3 py-2 text-sm font-medium text-fg-on-accent hover:opacity-90"
            >
              See the records
            </Link>
            {done.batch && (
              <Link
                to={`/activity?batch=${done.batch}`}
                className="inline-flex items-center rounded-md border border-border px-3 py-2 text-sm text-fg hover:bg-canvas-inset"
              >
                See what changed
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
