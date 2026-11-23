import { useQueryClient } from '@tanstack/react-query'
import { SaveToDriveDialog } from '../components/files/SaveToDrive'
import { useState, type ReactNode } from 'react'
import { useParams } from 'react-router'
import type {
  CollectionComparison,
  ComparedKind,
  ComparedRecord,
  Release,
  ReleaseVerify,
} from '../api/releases'
import { AuditChangeList } from '../components/audit/AuditChanges'
import { releasesApi } from '../api/releases'
import type { FlowContext } from '../components/files/fileFlows'
import { DrivePicker } from '../components/files/DrivePicker'
import { MethodStep, type Method } from '../components/exports/MethodStep'
import {
  EditReleaseDialog,
  WithdrawReleaseDialog,
  YankReleaseDialog,
} from '../components/releases/ReleaseDialogs'
import {
  compareRelease,
  deepVerify,
  exportRelease,
  gatherRelease,
  zipRelease,
} from '../components/releases/releaseFlows'
import {
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  useToast,
  Button,
  Card,
  DataTable,
  DEFAULT_PAGE_SIZES,
  DetailSkeleton,
  ErrorState,
  Page,
  Pagination,
  SegmentedControl,
  Spinner,
  TabNav,
  TabPanel,
  useTabParam,
  type DataTableColumn,
} from '../components/ui'
import { useDriveChoice } from '../hooks/useDriveChoice'
import { useFeatures } from '../hooks/useFeatures'
import { usePermissions } from '../hooks/useMe'
import {
  useRelease,
  useComparedRecords,
  useRecordDifferences,
  useReleaseComparison,
  useReleaseCitation,
  useReleaseFilePlan,
  useVerifyRelease,
} from '../hooks/useReleases'
import { errorMessage } from '../lib/errors'
import { pluralise } from '../lib/utils'
import { licenceName } from '../utils/licences'
import { formatBytes } from '../utils/restrictions'

const TABS = [
  { id: 'overview' as const, label: 'Overview' },
  { id: 'changes' as const, label: 'Changed since' },
]

/** One release: how to cite it, what it holds, getting its files out (a
 * folder, a drive, a zip while it is small), whether it still holds what it
 * was made with, and what has changed in the project since it was made. A
 * yanked release is only its record: no data, no files. */
export default function ReleasePage() {
  const { name = '' } = useParams()
  const { data: release, isLoading, error } = useRelease(name)
  const [tab, setTab] = useTabParam(TABS, 'overview')
  const { can, why } = usePermissions()
  const [editing, setEditing] = useState(false)
  const [withdrawing, setWithdrawing] = useState(false)
  const [yanking, setYanking] = useState(false)
  const [saving, setSaving] = useState(false)
  const [moving, setMoving] = useState(false)
  const features = useFeatures()
  const flow = useFlow()
  const allowed = can('release')
  const yanked = !!release?.yanked_at

  return (
    <Page
      breadcrumbs={[{ label: 'Releases', to: '/releases' }, { label: name }]}
      title={release ? `${release.name}: ${release.title}` : name}
      meta={release ? <Meta release={release} /> : undefined}
      loading={isLoading ? <DetailSkeleton /> : undefined}
      error={error ? <ErrorState message={errorMessage(error)} /> : undefined}
      secondaryActions={
        release
          ? [
              // The release as one file another civex reads, and where civex
              // itself keeps its files: neither is the export.
              ...(yanked
                ? []
                : [
                    {
                      label: 'Copy to another project…',
                      onClick: () => setSaving(true),
                    },
                    {
                      label: 'Change storage drive…',
                      onClick: () => setMoving(true),
                      disabled: !features.has('volumes'),
                    },
                  ]),
              {
                label: allowed
                  ? 'Edit details…'
                  : `Edit details (${why('release')})`,
                onClick: () => setEditing(true),
                disabled: !allowed || yanked,
              },
              {
                label: 'Withdraw…',
                onClick: () => setWithdrawing(true),
                variant: 'danger',
                disabled: !allowed || !!release.withdrawn_at,
              },
              {
                label: 'Yank…',
                onClick: () => setYanking(true),
                variant: 'danger',
                disabled: !allowed || yanked,
              },
            ]
          : undefined
      }
      tabs={
        <TabNav label="Release" value={tab} onChange={setTab} tabs={TABS} />
      }
    >
      {release && (
        <>
          <TabPanel id="overview" value={tab}>
            <div className="space-y-4">
              {release.yanked_at ? (
                <Card variant="danger" title="Yanked">
                  <p className="text-sm">
                    {new Date(release.yanked_at).toLocaleDateString()} by{' '}
                    {release.yanked_by ?? 'someone'}: {release.yanked_reason}.
                    Its data was given up; this is the record of what it was.
                  </p>
                </Card>
              ) : (
                release.withdrawn_at && (
                  <Card variant="danger" title="Withdrawn">
                    <p className="text-sm">
                      {new Date(release.withdrawn_at).toLocaleDateString()} by{' '}
                      {release.withdrawn_by ?? 'someone'}:{' '}
                      {release.withdrawn_reason}
                    </p>
                  </Card>
                )
              )}
              <Citation name={release.name} />
              <Manifest release={release} />
              {!yanked && <Files release={release} />}
              {!yanked && <Verify name={release.name} />}
            </div>
          </TabPanel>
          <TabPanel id="changes" value={tab}>
            <Changes release={release} />
          </TabPanel>
          {editing && (
            <EditReleaseDialog
              release={release}
              onClose={() => setEditing(false)}
            />
          )}
          {withdrawing && (
            <WithdrawReleaseDialog
              release={release}
              onClose={() => setWithdrawing(false)}
            />
          )}
          {yanking && (
            <YankReleaseDialog
              release={release}
              onClose={() => setYanking(false)}
            />
          )}
        </>
      )}
      {moving && release && (
        <StorageDriveDialog
          release={release}
          onClose={() => setMoving(false)}
          onChosen={(volume) => {
            setMoving(false)
            void gatherRelease(flow, release.name, volume)
          }}
        />
      )}
      {saving && release && (
        // Into a folder of this computer, where civex runs, or as a download.
        <SaveToDriveDialog
          title="Copy to another project"
          onSave={(folder) => releasesApi.save(release.name, folder)}
          onDownload={() => {
            const a = document.createElement('a')
            a.href = releasesApi.bundleUrl(release.name)
            a.download = release.file_name
            a.click()
          }}
          onClose={() => setSaving(false)}
        />
      )}
    </Page>
  )
}

function Meta({ release }: { release: Release }) {
  return (
    <span>
      Made {new Date(release.created_at).toLocaleString()}
      {release.created_by ? ` by ${release.created_by}` : ''}
      {release.yanked_at
        ? ' · yanked'
        : release.withdrawn_at
          ? ' · withdrawn'
          : ''}
    </span>
  )
}

type Form = 'text' | 'bibtex' | 'cff'

function Citation({ name }: { name: string }) {
  const { data, error } = useReleaseCitation(name)
  const [form, setForm] = useState<Form>('text')
  const [copied, setCopied] = useState(false)
  const text = data?.[form] ?? ''
  return (
    <Card
      title="Cite it"
      action={
        <Button
          size="sm"
          disabled={!text}
          onClick={() => {
            void navigator.clipboard?.writeText(text)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
        >
          {copied ? 'Copied' : 'Copy'}
        </Button>
      }
    >
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
        {error ? (
          <ErrorState message={errorMessage(error)} />
        ) : (
          <pre className="whitespace-pre-wrap break-words rounded-md bg-canvas-subtle p-3 text-sm">
            {text || '…'}
          </pre>
        )}
      </div>
    </Card>
  )
}

function Row({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-2 py-1">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

function covers(release: Release): string {
  if (release.scope.collections?.length)
    return `Collections: ${release.scope.collections.join(', ')}`
  if (release.scope.query)
    return 'The records a list showed (and those above them)'
  if (release.scope.records?.length)
    return `${pluralise(release.scope.records.length, 'chosen record')} (and those above them)`
  return 'The whole project'
}

function Manifest({ release }: { release: Release }) {
  const c = release.counts
  const n = (k: string) => Number(c[k] ?? 0)
  return (
    <Card title="What it holds">
      <dl className="text-sm">
        <Row label="Authors">
          {release.authors.length
            ? release.authors.map((a, i) => (
                <span key={i}>
                  {i > 0 && '; '}
                  {a.name}
                  {a.affiliation ? ` (${a.affiliation})` : ''}
                  {a.orcid && (
                    <>
                      {' '}
                      <a
                        className="text-accent underline"
                        href={`https://orcid.org/${a.orcid}`}
                      >
                        ORCID
                      </a>
                    </>
                  )}
                </span>
              ))
            : 'None given'}
        </Row>
        {release.description && (
          <Row label="Description">{release.description}</Row>
        )}
        <Row label="Licence">
          {release.licence
            ? `${release.licence}${licenceName(release.licence) ? ` (${licenceName(release.licence)})` : ''}`
            : 'None given'}
        </Row>
        {release.keywords.length > 0 && (
          <Row label="Keywords">{release.keywords.join(', ')}</Row>
        )}
        <Row label="DOI">
          {release.doi ? (
            <a
              className="text-accent underline"
              href={`https://doi.org/${release.doi}`}
            >
              {release.doi}
            </a>
          ) : (
            'None'
          )}
        </Row>
        <Row label="Covers">{covers(release)}</Row>
        <Row label="Holds">
          {pluralise(n('records'), 'record')},{' '}
          {pluralise(n('schemas'), 'schema')}, {pluralise(n('files'), 'file')}{' '}
          kept where they are ({formatBytes(n('file_bytes'))})
          {n('workflows') ? `, ${pluralise(n('workflows'), 'workflow')}` : ''}
        </Row>
        <Row label="Content hash">
          <code className="text-xs">{release.content_hash}</code>
        </Row>
        <Row label="Project copy">
          {formatBytes(release.bundle_size)} ·{' '}
          <code className="text-xs">{release.bundle_sha256.slice(0, 16)}…</code>
        </Row>
        <Row label="History position">
          {release.local_seq != null
            ? `Entry ${release.local_seq} here`
            : 'Not known here'}
          {release.feed_seq != null
            ? ` · server number ${release.feed_seq}`
            : ''}
        </Row>
        <Row label="Made with">civex {release.civex_version}</Row>
      </dl>
      {!release.yanked_at && (
        <p className="mt-3 text-xs text-fg-muted">
          Collections → Bring in from another project… reads it back.
        </p>
      )}
    </Card>
  )
}

function useFlow(): FlowContext {
  const toast = useToast()
  const qc = useQueryClient()
  return { toast, qc, problem: () => undefined }
}

function Verify({ name }: { name: string }) {
  const verify = useVerifyRelease(name)
  const flow = useFlow()
  const [deep, setDeep] = useState<ReleaseVerify | null>(null)
  const r = deep ?? verify.data
  return (
    <Card
      title="Check it"
      action={
        <div className="flex gap-2">
          <Button
            size="sm"
            disabled={verify.isPending}
            onClick={() => {
              setDeep(null)
              verify.mutate()
            }}
          >
            {verify.isPending ? 'Checking…' : 'Verify'}
          </Button>
          <Button
            size="sm"
            title="Read every file back against its hash: long for a large release"
            onClick={() => void deepVerify(flow, name, setDeep)}
          >
            Read every file back
          </Button>
        </div>
      }
    >
      {verify.isPending ? (
        <p className="flex items-center gap-2 text-sm text-fg-muted">
          <Spinner /> Reading the records back…
        </p>
      ) : verify.error ? (
        <ErrorState message={errorMessage(verify.error)} />
      ) : r ? (
        r.matches ? (
          <p className="text-sm text-success" role="status">
            Intact: its records are exactly what it was made with, and all{' '}
            {pluralise(r.files, 'file')} it cites are kept here
            {r.deep ? `, every one read back against its hash` : ''}.
            {r.notes.map((n) => ` ${n}`)}
          </p>
        ) : (
          <div className="text-sm text-danger" role="alert">
            <p>It does not match.</p>
            <ul className="list-disc pl-5">
              {r.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        )
      ) : (
        <p className="text-sm text-fg-muted">
          Recompute the content hash from its records and the files they cite,
          and check every file is kept here. Reading every file back takes
          longer.
        </p>
      )}
    </Card>
  )
}

/** Getting the release out is the point of it: one **Export…**, the same
 * two ways as any export (save to a folder, or a zip while it is small
 * enough), with the records beside the files in the form civex reads back. */
function Files({ release }: { release: Release }) {
  const flow = useFlow()
  const plan = useReleaseFilePlan(release.name)
  const [exporting, setExporting] = useState(false)
  const [method, setMethod] = useState<Method>('link')
  const p = plan.data
  const files = Number(release.counts.files ?? 0)

  function go() {
    if (method === 'zip') void zipRelease(flow, release.name)
    else void exportRelease(flow, release.name)
    setExporting(false)
  }

  return (
    <Card
      title="Its files"
      action={
        <Button size="sm" variant="primary" onClick={() => setExporting(true)}>
          Export…
        </Button>
      }
    >
      {files === 0 ? (
        <p className="text-sm text-fg-muted">No files</p>
      ) : plan.error ? (
        <ErrorState message={errorMessage(plan.error)} />
      ) : !p ? (
        <Spinner />
      ) : (
        <div className="space-y-1 text-sm">
          <p>{p.summary}</p>
          {p.unavailable.map((g) => (
            <p key={g.volume ?? '-'} className="text-attention">
              {pluralise(g.files, 'file')} on {g.volume ?? 'no drive here'}:{' '}
              {g.reason} {g.fix}
            </p>
          ))}
        </div>
      )}
      {exporting && (
        <Modal onClose={() => setExporting(false)} size="md">
          <ModalHeader onClose={() => setExporting(false)}>
            Export {release.name}
          </ModalHeader>
          <ModalBody className="space-y-3">
            <MethodStep
              method={method}
              setMethod={setMethod}
              zip={!!p?.zip_allowed}
            />
          </ModalBody>
          <ModalFooter>
            <Button onClick={() => setExporting(false)}>Cancel</Button>
            <Button variant="primary" onClick={go}>
              Export
            </Button>
          </ModalFooter>
        </Modal>
      )}
    </Card>
  )
}

/** Housekeeping, not an export: which drive civex itself keeps the release's
 * files on (the one drive-and-free-space rule). */
function StorageDriveDialog({
  release,
  onClose,
  onChosen,
}: {
  release: Release
  onClose: () => void
  onChosen: (volume: string) => void
}) {
  const [chosen, setChosen] = useState<string | null>(null)
  const drive = useDriveChoice({ need: 0, allowProject: false, chosen })
  return (
    <Modal onClose={onClose} size="sm">
      <ModalHeader onClose={onClose}>
        Storage drive for {release.name}
      </ModalHeader>
      <ModalBody>
        <div className="space-y-3 text-sm">
          <DrivePicker
            label="Drive"
            value={drive.target}
            targets={drive.targets}
            allowProject={false}
            need={0}
            free={drive.free}
            tooBig={drive.tooBig}
            onChange={setChosen}
          />
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="primary"
          disabled={!drive.target}
          onClick={() => onChosen(drive.target)}
        >
          Move
        </Button>
      </ModalFooter>
    </Modal>
  )
}

const KIND_WORDS: Record<ComparedKind, string> = {
  added: 'added',
  changed: 'changed',
  removed: 'removed',
}

/** The release compared with the data now, record by record (never from
 * history, so every copy says the same): counts per collection, each opening
 * the records it means, and the schemas and fields changed since. A large
 * release is compared as a job in the status bar. */
function Changes({ release }: { release: Release }) {
  const name = release.name
  const background = release.compare_in_background
  const flow = useFlow()
  const { data, isLoading, error } = useReleaseComparison(name, !background)
  const [picked, setPicked] = useState<{
    kind: ComparedKind
    collection?: string
  } | null>(null)
  if (isLoading) return <Spinner />
  if (error) return <ErrorState message={errorMessage(error)} />
  if (!data)
    return (
      <div className="space-y-2">
        <p className="text-sm text-fg-muted">
          It holds {pluralise(Number(release.counts.records ?? 0), 'record')}:
          comparing them with the data now takes a while.
        </p>
        <Button onClick={() => void compareRelease(flow, name)}>
          Compare with the data now
        </Button>
      </div>
    )
  const count = (
    n: number,
    kind: ComparedKind,
    collection?: string,
  ): ReactNode =>
    n ? (
      <Button
        size="sm"
        variant="ghost"
        title={`Show the ${pluralise(n, 'record')} ${KIND_WORDS[kind]}`}
        onClick={() => setPicked({ kind, collection })}
      >
        {n.toLocaleString()}
      </Button>
    ) : (
      <span className="text-fg-muted">0</span>
    )
  const columns: DataTableColumn<CollectionComparison>[] = [
    {
      key: 'collection',
      header: 'Collection',
      render: (c) =>
        (c.collection ?? 'Gone') + (c.in_scope ? '' : ' (not in the release)'),
    },
    {
      key: 'added',
      header: 'Added',
      align: 'right',
      rawCell: true,
      render: (c) => count(c.added, 'added', c.collection_id),
    },
    {
      key: 'changed',
      header: 'Changed',
      align: 'right',
      rawCell: true,
      render: (c) => count(c.changed, 'changed', c.collection_id),
    },
    {
      key: 'removed',
      header: 'Removed',
      align: 'right',
      rawCell: true,
      render: (c) => count(c.removed, 'removed', c.collection_id),
    },
  ]
  const nothing =
    !data.added && !data.changed && !data.removed && !data.structure.length
  return (
    <div className="space-y-3">
      <p className="text-sm">
        {nothing
          ? `Nothing has changed since this release: its ${pluralise(data.records, 'record')} are as they were.`
          : `${data.unchanged.toLocaleString()} of its ${pluralise(data.records, 'record')} are as they were.`}
      </p>
      {!nothing && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {(['added', 'changed', 'removed'] as const).map((k) => (
            <span key={k} className="flex items-center gap-1">
              {count(data[k], k)} {KIND_WORDS[k]}
            </span>
          ))}
        </div>
      )}
      {data.collections.length > 0 && (
        <DataTable
          dense
          layout="auto"
          columns={columns}
          rows={data.collections}
          getRowId={(c) => c.collection_id}
        />
      )}
      {picked && (
        <ComparedRecords
          name={name}
          kind={picked.kind}
          collection={picked.collection}
          collectionName={
            data.collections.find((c) => c.collection_id === picked.collection)
              ?.collection ?? undefined
          }
          onClose={() => setPicked(null)}
        />
      )}
      {data.structure.length > 0 && (
        <Card title="Schemas and fields since">
          <ul className="space-y-1 text-sm">
            {data.structure.map((c, i) => (
              <li key={i}>
                {c.kind === 'field'
                  ? `Field ${c.name} of ${c.schema}`
                  : `Schema ${c.name}`}{' '}
                {c.change}
                {c.what.length ? ` (${c.what.join(', ')})` : ''}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}

/** The records one count means, a page at a time: an added or changed one
 * opens as it is now (a changed one first says which fields differ), a
 * removed one is read from the release. */
function ComparedRecords({
  name,
  kind,
  collection,
  collectionName,
  onClose,
}: {
  name: string
  kind: ComparedKind
  collection?: string
  collectionName?: string
  onClose: () => void
}) {
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZES[0])
  const [open, setOpen] = useState<ComparedRecord | null>(null)
  const { data, isLoading, error } = useComparedRecords(
    name,
    kind,
    page,
    pageSize,
    collection,
  )
  const columns: DataTableColumn<ComparedRecord>[] = [
    { key: 'name', header: 'Record', render: (r) => r.name ?? r.id },
    { key: 'schema', header: 'Kind', render: (r) => r.schema ?? '' },
    {
      key: 'collection',
      header: 'Collection',
      render: (r) => r.collection ?? '',
    },
  ]
  return (
    <Card
      title={`Records ${KIND_WORDS[kind]}${collectionName ? ` in ${collectionName}` : ''}`}
      action={
        <Button size="sm" onClick={onClose}>
          Close
        </Button>
      }
    >
      <DataTable
        dense
        layout="auto"
        columns={columns}
        rows={data?.items ?? []}
        isLoading={isLoading}
        error={error ? errorMessage(error) : undefined}
        getRowId={(r) => r.id}
        rowHref={kind === 'added' ? (r) => `/records/${r.id}` : undefined}
        onRowClick={kind === 'changed' ? (r) => setOpen(r) : undefined}
        emptyTitle="None"
        emptyMessage={
          kind === 'removed'
            ? 'Every record it holds is still here.'
            : 'Nothing here.'
        }
        footer={
          data && data.total > pageSize ? (
            <Pagination
              page={page}
              pageSize={pageSize}
              total={data.total}
              onPage={setPage}
              onPageSize={(n) => {
                setPageSize(n)
                setPage(0)
              }}
            />
          ) : undefined
        }
      />
      {open && (
        <RecordDifferences
          name={name}
          record={open}
          onClose={() => setOpen(null)}
        />
      )}
    </Card>
  )
}

function RecordDifferences({
  name,
  record,
  onClose,
}: {
  name: string
  record: ComparedRecord
  onClose: () => void
}) {
  const { data, isLoading, error } = useRecordDifferences(name, record.id)
  return (
    <Modal onClose={onClose} size="lg">
      <ModalHeader onClose={onClose}>
        {record.name ?? record.id}: in the release and now
      </ModalHeader>
      <ModalBody>
        {isLoading ? (
          <Spinner />
        ) : error ? (
          <ErrorState message={errorMessage(error)} />
        ) : (
          <AuditChangeList changes={data ?? []} action="update" />
        )}
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Close</Button>
        <Button variant="primary" to={`/records/${record.id}`}>
          Open the record
        </Button>
      </ModalFooter>
    </Modal>
  )
}
