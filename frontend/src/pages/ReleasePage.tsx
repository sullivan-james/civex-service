import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router'
import type { Release, ReleaseChanges, ReleaseVerify } from '../api/releases'
import { releasesApi } from '../api/releases'
import type { FlowContext } from '../components/files/fileFlows'
import { DrivePicker } from '../components/files/DrivePicker'
import {
  EditReleaseDialog,
  WithdrawReleaseDialog,
  YankReleaseDialog,
} from '../components/releases/ReleaseDialogs'
import {
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
  DetailSkeleton,
  ErrorState,
  Page,
  SegmentedControl,
  Spinner,
  TabNav,
  TabPanel,
  useTabParam,
  type DataTableColumn,
} from '../components/ui'
import { PROJECT, useDriveChoice } from '../hooks/useDriveChoice'
import { useFeatures } from '../hooks/useFeatures'
import { usePermissions } from '../hooks/useMe'
import {
  useRelease,
  useReleaseChanges,
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
  const allowed = can('change_structure')
  const yanked = !!release?.yanked_at

  return (
    <Page
      breadcrumbs={[{ label: 'Releases', to: '/releases' }, { label: name }]}
      title={release ? `${release.name}: ${release.title}` : name}
      meta={release ? <Meta release={release} /> : undefined}
      loading={isLoading ? <DetailSkeleton /> : undefined}
      error={error ? <ErrorState message={errorMessage(error)} /> : undefined}
      action={
        release &&
        !yanked && (
          <Button
            href={releasesApi.bundleUrl(release.name)}
            download={release.file_name}
          >
            Download
          </Button>
        )
      }
      secondaryActions={
        release
          ? [
              {
                label: allowed
                  ? 'Edit details…'
                  : `Edit details (${why('change_structure')})`,
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
            <Changes name={release.name} />
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
        <Row label="Bundle">
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
          To get the records back as they were, download the bundle and import
          it into a new project (Collections → Import bundle…); the files come
          out below.
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

/** Getting the release's files out, the way any export does: a folder to
 * open on the drive holding most of them, copies on a chosen drive, all of
 * them moved onto one drive, or a zip while it is small enough to download. */
function Files({ release }: { release: Release }) {
  const flow = useFlow()
  const plan = useReleaseFilePlan(release.name)
  const features = useFeatures()
  const [picking, setPicking] = useState<'copy' | 'move' | null>(null)
  const p = plan.data
  const files = Number(release.counts.files ?? 0)
  return (
    <Card
      title="Its files"
      action={
        files > 0 && (
          <div className="flex flex-wrap gap-2">
            {features.has('open_folder') && (
              <Button
                size="sm"
                onClick={() => void exportRelease(flow, release.name, 'link')}
              >
                Open as a folder
              </Button>
            )}
            <Button size="sm" onClick={() => setPicking('copy')}>
              Put on a drive…
            </Button>
            {features.has('volumes') && (
              <Button size="sm" onClick={() => setPicking('move')}>
                Move to drive…
              </Button>
            )}
            {p?.zip_allowed && (
              <Button
                size="sm"
                onClick={() => void zipRelease(flow, release.name)}
              >
                Download as a zip
              </Button>
            )}
          </div>
        )
      }
    >
      {files === 0 ? (
        <p className="text-sm text-fg-muted">Its records cite no files.</p>
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
          {!p.zip_allowed && (
            <p className="text-fg-muted">
              Too large to download as one zip: make a folder of it on a drive.
            </p>
          )}
          <p className="text-xs text-fg-muted">
            A folder holds them in a folder per record, as the records were,
            with manifest-sha256.txt (each file&apos;s hash), release.json and
            CITATION.cff beside them.
          </p>
        </div>
      )}
      {picking && (
        <DriveDialog
          kind={picking}
          release={release}
          need={p?.bytes ?? 0}
          holding={p?.link_volume ?? undefined}
          onClose={() => setPicking(null)}
          onChosen={(volume) => {
            setPicking(null)
            if (picking === 'move')
              void gatherRelease(flow, release.name, volume)
            else
              void exportRelease(
                flow,
                release.name,
                'copy',
                volume === PROJECT ? undefined : volume,
              )
          }}
        />
      )}
    </Card>
  )
}

/** Which drive: the one drive-and-free-space rule. */
function DriveDialog({
  kind,
  release,
  need,
  holding,
  onClose,
  onChosen,
}: {
  kind: 'copy' | 'move'
  release: Release
  need: number
  holding?: string
  onClose: () => void
  onChosen: (volume: string) => void
}) {
  const [chosen, setChosen] = useState<string | null>(null)
  const allowProject = kind === 'copy'
  const drive = useDriveChoice({ holding, need, allowProject, chosen })
  return (
    <Modal onClose={onClose} size="sm">
      <ModalHeader onClose={onClose}>
        {kind === 'copy'
          ? `Put the files of ${release.name} on a drive`
          : `Move the files of ${release.name} to one drive`}
      </ModalHeader>
      <ModalBody>
        <div className="space-y-3 text-sm">
          <DrivePicker
            label="Drive"
            value={drive.target}
            targets={drive.targets}
            allowProject={allowProject}
            need={need}
            free={drive.free}
            tooBig={drive.tooBig}
            onChange={setChosen}
          />
          <p className="text-fg-muted">
            {kind === 'copy'
              ? 'A folder of copies, laid out as the records were, with the manifest and citation.'
              : 'The release then keeps its files on that drive. Records that use them elsewhere keep theirs.'}
          </p>
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="primary"
          disabled={!drive.target || drive.tooBig}
          onClick={() => onChosen(drive.target)}
        >
          {kind === 'copy' ? 'Copy' : 'Move'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}

function Changes({ name }: { name: string }) {
  const { data, isLoading, error } = useReleaseChanges(name)
  if (isLoading) return <Spinner />
  if (error) return <ErrorState message={errorMessage(error)} />
  if (!data) return null
  if (!data.comparable)
    return <p className="text-sm text-fg-muted">{data.reason}</p>
  const columns: DataTableColumn<ReleaseChanges['collections'][number]>[] = [
    {
      key: 'collection',
      header: 'Collection',
      render: (c) =>
        (c.collection ?? 'Deleted for good') +
        (c.in_scope ? '' : ' (not in the release)'),
    },
    { key: 'added', header: 'Added', align: 'right', render: (c) => c.added },
    {
      key: 'changed',
      header: 'Changed',
      align: 'right',
      render: (c) => c.changed,
    },
    {
      key: 'deleted',
      header: 'Deleted',
      align: 'right',
      render: (c) => c.deleted,
    },
  ]
  const structure = Object.entries(data.structure)
  const nothing =
    !data.added && !data.changed && !data.deleted && !structure.length
  return (
    <div className="space-y-3">
      <p className="text-sm">
        {nothing
          ? 'Nothing has changed since this release.'
          : `Since this release: ${pluralise(data.added, 'record')} added, ${data.changed} changed, ${data.deleted} deleted.`}
      </p>
      {!nothing && (
        <DataTable
          dense
          layout="auto"
          columns={columns}
          rows={data.collections}
          getRowId={(c) => c.collection_id ?? 'gone'}
          emptyTitle="No records changed"
          emptyMessage="Only the structure changed."
        />
      )}
      {structure.length > 0 && (
        <p className="text-sm text-fg-muted">
          Other changes: {structure.map(([k, v]) => `${v} to ${k}s`).join(', ')}
          .
        </p>
      )}
    </div>
  )
}
