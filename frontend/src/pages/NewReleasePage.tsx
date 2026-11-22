import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import type {
  ReleaseAuthor,
  ReleaseMetadata,
  ReleasePlan,
  ReleaseScopeBody,
} from '../api/releases'
import {
  Button,
  Card,
  DataTable,
  Field,
  FormError,
  Input,
  MultiPick,
  Page,
  SegmentedControl,
  Select,
  Spinner,
  Stepper,
  Textarea,
  useToast,
  type DataTableColumn,
} from '../components/ui'
import { AuthorsField } from '../components/releases/AuthorsField'
import { useBack } from '../hooks/useBack'
import { useCollections } from '../hooks/useCollections'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { usePermissions } from '../hooks/useMe'
import {
  useCitationPreview,
  useCreateRelease,
  useReleasePlan,
} from '../hooks/useReleases'
import { useAllViews } from '../hooks/useViews'
import { errorMessage } from '../lib/errors'
import { pluralise } from '../lib/utils'
import { SPDX_LICENCES, licenceName } from '../utils/licences'
import { formatSize } from '../utils/storage'

type StepId = 'what' | 'citation' | 'review'
const STEPS: { id: StepId; label: string }[] = [
  { id: 'what', label: 'What' },
  { id: 'citation', label: 'Citation' },
  { id: 'review', label: 'Review' },
]

type Covers = 'project' | 'collections' | 'list' | 'chosen'
type Form = 'text' | 'bibtex' | 'cff'

/** What the explorer handed over with **Release these…**: the ticked records
 * (`?records=a,b`), or everything its list showed (`?query=` as JSON). */
function chosenFrom(params: URLSearchParams): ReleaseScopeBody | null {
  const records = params.get('records')
  if (records) return { records: records.split(',').filter(Boolean) }
  const query = params.get('query')
  if (query) {
    try {
      return { query: JSON.parse(query) as Record<string, unknown> }
    } catch {
      return null
    }
  }
  return null
}

/** Make a release, on a page of its own (`/releases/new`): what it covers,
 * how it is cited (with the citation as it will read), and a review of what
 * it would hold, all from the catalog, before anything is made. The records
 * are frozen in a small bundle; the files they cite are kept where they are,
 * so a release of terabytes is made in moments. */
export default function NewReleasePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const back = useBack('/releases')
  const toast = useToast()
  const { can, why } = usePermissions()
  const chosen = useMemo(() => chosenFrom(params), [params])
  const [step, setStep] = useState<StepId>('what')

  // What it covers.
  const [covers, setCovers] = useState<Covers>(
    chosen ? 'chosen' : params.get('collection') ? 'collections' : 'project',
  )
  const [collections, setCollections] = useState<string[]>(
    params.get('collection') ? [params.get('collection') as string] : [],
  )
  const [viewId, setViewId] = useState('')
  const [viewCollection, setViewCollection] = useState('')
  const { data: allCollections = [] } = useCollections()
  const { data: views = [] } = useAllViews(covers === 'list')
  const view = views.find((v) => v.id === viewId)

  // How it is cited.
  const [name, setName] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [authors, setAuthors] = useState<ReleaseAuthor[]>([{ name: '' }])
  const [licence, setLicence] = useState('')
  const [doi, setDoi] = useState('')
  const [keywords, setKeywords] = useState('')

  const scope: ReleaseScopeBody | null =
    covers === 'project'
      ? {}
      : covers === 'collections'
        ? collections.length
          ? { collections }
          : null
        : covers === 'list'
          ? view
            ? {
                query: {
                  collection: viewCollection || null,
                  schema_name: view.schema_name,
                  filter: view.filter_tree,
                },
              }
            : null
          : chosen
  const plan = useReleasePlan(scope ?? {}, !!scope)

  const metadata: ReleaseMetadata = {
    title: title.trim(),
    description: description.trim() || null,
    authors: authors
      .map((a) => ({
        name: a.name.trim(),
        orcid: a.orcid?.trim() || undefined,
        affiliation: a.affiliation?.trim() || undefined,
      }))
      .filter((a) => a.name),
    licence: licence.trim() || null,
    doi: doi.trim() || null,
    keywords: keywords
      .split(',')
      .map((k) => k.trim())
      .filter(Boolean),
  }
  const create = useCreateRelease()
  const allowed = can('change_structure')
  const citationReady = !!name.trim() && !!title.trim()

  function make() {
    if (!scope) return
    create.mutate(
      { ...scope, ...metadata, name: name.trim(), title: title.trim() },
      {
        onSuccess: (made) => {
          toast.success(`Release ${made.name} made`)
          navigate(`/releases/${encodeURIComponent(made.name)}`, {
            replace: true,
          })
        },
      },
    )
  }

  const at = STEPS.findIndex((s) => s.id === step)
  const canNext =
    step === 'what'
      ? !!scope && !!plan.data
      : step === 'citation' && citationReady

  return (
    <Page
      breadcrumbs={[
        { label: 'Releases', to: '/releases' },
        { label: 'New release' },
      ]}
      title="New release"
      info="A release freezes the records as they are now, with a version, a citation and a content hash. The files they cite stay where they are: the release keeps them, so they are never cleaned up while it exists."
    >
      <div className="max-w-4xl space-y-6">
        <Stepper steps={STEPS} activeIndex={at} />

        <div className="min-h-56 space-y-5">
          {step === 'what' && (
            <WhatStep
              covers={covers}
              setCovers={setCovers}
              hasChosen={!!chosen}
              chosen={chosen}
              collections={collections}
              setCollections={setCollections}
              collectionNames={allCollections.map((c) => c.name)}
              views={views.map((v) => ({
                id: v.id,
                label: `${v.name} (${v.schema_name})`,
              }))}
              viewId={viewId}
              setViewId={setViewId}
              viewCollection={viewCollection}
              setViewCollection={setViewCollection}
              plan={scope ? plan.data : undefined}
              planError={plan.error}
              waiting={!!scope && plan.isLoading}
            />
          )}
          {step === 'citation' && (
            <CitationStep
              name={name}
              setName={setName}
              title={title}
              setTitle={setTitle}
              description={description}
              setDescription={setDescription}
              authors={authors}
              setAuthors={setAuthors}
              licence={licence}
              setLicence={setLicence}
              doi={doi}
              setDoi={setDoi}
              keywords={keywords}
              setKeywords={setKeywords}
              metadata={metadata}
            />
          )}
          {step === 'review' && plan.data && (
            <ReviewStep plan={plan.data} name={name.trim()} />
          )}
          {create.error && <FormError message={errorMessage(create.error)} />}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border-muted pt-4">
          <Button onClick={back}>Cancel</Button>
          {at > 0 && (
            <Button onClick={() => setStep(STEPS[at - 1].id)}>Back</Button>
          )}
          {step !== 'review' ? (
            <Button
              variant="primary"
              disabled={!canNext}
              onClick={() => setStep(STEPS[at + 1].id)}
            >
              Next
            </Button>
          ) : (
            <Button
              variant="primary"
              disabled={
                !allowed ||
                !citationReady ||
                !scope ||
                create.isPending ||
                (plan.data?.unsent ?? 0) > 0
              }
              title={allowed ? undefined : why('change_structure')}
              onClick={make}
            >
              {create.isPending ? 'Making…' : 'Make release'}
            </Button>
          )}
        </div>
      </div>
    </Page>
  )
}

function WhatStep(props: {
  covers: Covers
  setCovers: (c: Covers) => void
  hasChosen: boolean
  chosen: ReleaseScopeBody | null
  collections: string[]
  setCollections: (c: string[]) => void
  collectionNames: string[]
  views: { id: string; label: string }[]
  viewId: string
  setViewId: (v: string) => void
  viewCollection: string
  setViewCollection: (v: string) => void
  plan: ReleasePlan | undefined
  planError: unknown
  waiting: boolean
}) {
  const options: { value: Covers; label: string }[] = [
    { value: 'project', label: 'The whole project' },
    { value: 'collections', label: 'Some collections' },
    { value: 'list', label: 'A saved list' },
  ]
  if (props.hasChosen)
    options.push({ value: 'chosen', label: 'The records chosen' })
  const p = props.plan
  return (
    <>
      <SegmentedControl
        label="What it covers"
        value={props.covers}
        onChange={props.setCovers}
        options={options}
      />
      {props.covers === 'collections' && (
        <MultiPick
          label="Collections"
          options={props.collectionNames.map((n) => ({ value: n, label: n }))}
          value={props.collections}
          onChange={props.setCollections}
        />
      )}
      {props.covers === 'list' && (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Saved list">
            <Select
              value={props.viewId}
              onChange={(e) => props.setViewId(e.target.value)}
            >
              <option value="">Choose a saved list…</option>
              {props.views.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="In">
            <Select
              value={props.viewCollection}
              onChange={(e) => props.setViewCollection(e.target.value)}
            >
              <option value="">Every collection</option>
              {props.collectionNames.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      )}
      {props.covers === 'chosen' && props.chosen && (
        <p className="text-sm text-fg-muted">
          {props.chosen.records
            ? `The ${pluralise(props.chosen.records.length, 'record')} ticked, with what is inside them`
            : 'The records listed, with what is inside them'}
        </p>
      )}
      {props.planError ? (
        <FormError message={errorMessage(props.planError)} />
      ) : props.waiting ? (
        <p className="flex items-center gap-2 text-sm text-fg-muted">
          <Spinner /> Counting…
        </p>
      ) : p ? (
        <p className="text-sm text-fg" data-testid="release-plan">
          {pluralise(p.records, 'record')} in{' '}
          {pluralise(Object.keys(p.collections).length, 'collection')}, citing{' '}
          {pluralise(p.files, 'file')} ({formatSize(p.file_bytes)}). The files
          stay where they are.
        </p>
      ) : null}
    </>
  )
}

function CitationStep(props: {
  name: string
  setName: (v: string) => void
  title: string
  setTitle: (v: string) => void
  description: string
  setDescription: (v: string) => void
  authors: ReleaseAuthor[]
  setAuthors: (a: ReleaseAuthor[]) => void
  licence: string
  setLicence: (v: string) => void
  doi: string
  setDoi: (v: string) => void
  keywords: string
  setKeywords: (v: string) => void
  metadata: ReleaseMetadata
}) {
  const [form, setForm] = useState<Form>('text')
  // Debounced as text: a fresh object each render would never settle.
  const wanted = JSON.parse(
    useDebouncedValue(
      JSON.stringify({ ...props.metadata, name: props.name.trim() }),
      400,
    ),
  ) as ReleaseMetadata & { name: string }
  const preview = useCitationPreview(wanted, !!wanted.title)
  const known = licenceName(props.licence)
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Field
            label="Version"
            required
            info="What people cite, e.g. v1 or 2026-thesis. It can't be changed later."
          >
            <Input
              value={props.name}
              onChange={(e) => props.setName(e.target.value)}
              placeholder="v1"
            />
          </Field>
          <Field
            label="DOI"
            info="If the data has one, e.g. 10.1234/abcd. It can be added later."
          >
            <Input
              value={props.doi}
              onChange={(e) => props.setDoi(e.target.value)}
            />
          </Field>
        </div>
        <Field label="Title" required>
          <Input
            value={props.title}
            onChange={(e) => props.setTitle(e.target.value)}
          />
        </Field>
        <Field label="Description">
          <Textarea
            rows={3}
            value={props.description}
            onChange={(e) => props.setDescription(e.target.value)}
          />
        </Field>
        <AuthorsField authors={props.authors} onChange={props.setAuthors} />
        <div className="grid grid-cols-2 gap-3">
          <Field
            label="Licence"
            info="Type to find a licence by its SPDX id or name, or write any other."
          >
            <Input
              list="release-licences"
              value={props.licence}
              placeholder="CC-BY-4.0"
              onChange={(e) => props.setLicence(e.target.value)}
            />
          </Field>
          <Field label="Keywords" info="Separated by commas.">
            <Input
              value={props.keywords}
              placeholder="seals, acoustics"
              onChange={(e) => props.setKeywords(e.target.value)}
            />
          </Field>
        </div>
        <datalist id="release-licences">
          {SPDX_LICENCES.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </datalist>
        {props.licence.trim() && (
          <p className="text-xs text-fg-muted">
            {known ?? 'Not an SPDX id: it is cited as written.'}
          </p>
        )}
      </div>
      <Card title="How it will be cited">
        <div className="space-y-3">
          <SegmentedControl
            label="Citation format"
            size="sm"
            value={form}
            onChange={setForm}
            options={[
              { value: 'text', label: 'Text' },
              { value: 'bibtex', label: 'BibTeX' },
              { value: 'cff', label: 'CITATION.cff' },
            ]}
          />
          {preview.error ? (
            <FormError message={errorMessage(preview.error)} />
          ) : (
            <pre
              className="whitespace-pre-wrap break-words rounded-md bg-canvas-subtle p-3 text-xs"
              data-testid="citation-preview"
            >
              {preview.data?.[form] ?? 'Give it a title to see the citation.'}
            </pre>
          )}
          <p className="text-xs text-fg-muted">
            The content hash is added when it is made.
          </p>
        </div>
      </Card>
    </div>
  )
}

function ReviewStep({ plan, name }: { plan: ReleasePlan; name: string }) {
  const collections: DataTableColumn<[string, number]>[] = [
    { key: 'c', header: 'Collection', render: ([c]) => c },
    {
      key: 'n',
      header: 'Records',
      align: 'right',
      render: ([, n]) => n.toLocaleString(),
    },
  ]
  const drives: DataTableColumn<ReleasePlan['by_drive'][number]>[] = [
    {
      key: 'v',
      header: 'Drive',
      render: (d) => d.volume ?? 'Not on this computer',
    },
    {
      key: 'f',
      header: 'Files',
      align: 'right',
      render: (d) => d.files.toLocaleString(),
    },
    {
      key: 'b',
      header: 'Size',
      align: 'right',
      render: (d) => formatSize(d.bytes),
    },
  ]
  return (
    <div className="space-y-4">
      <p className="text-sm">
        {name || 'It'} will hold {pluralise(plan.records, 'record')} and{' '}
        {pluralise(plan.schemas, 'schema')}
        {plan.workflows ? `, ${pluralise(plan.workflows, 'workflow')}` : ''},
        and keep the {pluralise(plan.files, 'file')} they cite (
        {formatSize(plan.file_bytes)}) where they are. Once made it never
        changes.
      </p>
      {plan.unsent > 0 && (
        <p className="text-sm text-danger" role="alert">
          {pluralise(plan.unsent, 'change')} here hasn&apos;t reached the server
          yet: sync first, so the release is taken at a point everyone shares.
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Records">
          <DataTable
            dense
            layout="auto"
            columns={collections}
            rows={Object.entries(plan.collections)}
            getRowId={([c]) => c}
            emptyTitle="No records"
            emptyMessage="There is nothing to release yet."
          />
        </Card>
        <Card title="Files">
          <DataTable
            dense
            layout="auto"
            columns={drives}
            rows={plan.by_drive}
            getRowId={(d) => d.volume ?? '-'}
            emptyTitle="No files"
            emptyMessage="The records cite no files."
          />
        </Card>
      </div>
      <p className="text-sm text-fg-muted">
        Taken at history entry {plan.local_seq.toLocaleString()}
        {plan.feed_seq != null
          ? `, the server's number ${plan.feed_seq.toLocaleString()}`
          : ''}
        .
      </p>
    </div>
  )
}
