import { useState } from 'react'
import { useParams } from 'react-router'
import type { Release, ReleaseChanges } from '../api/releases'
import { releasesApi } from '../api/releases'
import {
  EditReleaseDialog,
  WithdrawReleaseDialog,
} from '../components/releases/ReleaseDialogs'
import {
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
import { usePermissions } from '../hooks/useMe'
import {
  useRelease,
  useReleaseChanges,
  useReleaseCitation,
  useVerifyRelease,
} from '../hooks/useReleases'
import { errorMessage } from '../lib/errors'
import { pluralise } from '../lib/utils'
import { formatBytes } from '../utils/restrictions'

const TABS = [
  { id: 'overview' as const, label: 'Overview' },
  { id: 'changes' as const, label: 'Changed since' },
]

/** One release: how to cite it, what it holds, whether its bundle still
 * holds that, and what has changed in the project since it was made. */
export default function ReleasePage() {
  const { name = '' } = useParams()
  const { data: release, isLoading, error } = useRelease(name)
  const [tab, setTab] = useTabParam(TABS, 'overview')
  const { can, why } = usePermissions()
  const [editing, setEditing] = useState(false)
  const [withdrawing, setWithdrawing] = useState(false)
  const allowed = can('change_structure')

  return (
    <Page
      breadcrumbs={[{ label: 'Releases', to: '/releases' }, { label: name }]}
      title={release ? `${release.name}: ${release.title}` : name}
      meta={release ? <Meta release={release} /> : undefined}
      loading={isLoading ? <DetailSkeleton /> : undefined}
      error={error ? <ErrorState message={errorMessage(error)} /> : undefined}
      action={
        release && (
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
                disabled: !allowed,
              },
              {
                label: 'Withdraw…',
                onClick: () => setWithdrawing(true),
                variant: 'danger',
                disabled: !allowed || !!release.withdrawn_at,
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
              {release.withdrawn_at && (
                <Card variant="danger" title="Withdrawn">
                  <p className="text-sm">
                    {new Date(release.withdrawn_at).toLocaleDateString()} by{' '}
                    {release.withdrawn_by ?? 'someone'}:{' '}
                    {release.withdrawn_reason}
                  </p>
                </Card>
              )}
              <Citation name={release.name} />
              <Manifest release={release} />
              <Verify name={release.name} />
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
      {release.withdrawn_at ? ' · withdrawn' : ''}
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
    return 'The records a query listed (and those above them)'
  return 'The whole project'
}

function Manifest({ release }: { release: Release }) {
  const c = release.counts
  const n = (k: string) => Number(c[k] ?? 0)
  return (
    <Card title="What it holds">
      <dl className="text-sm">
        <Row label="Authors">{release.authors.join('; ') || 'None given'}</Row>
        {release.description && (
          <Row label="Description">{release.description}</Row>
        )}
        <Row label="Licence">{release.licence ?? 'None given'}</Row>
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
          {pluralise(n('schemas'), 'schema')},{' '}
          {release.include_files
            ? `${pluralise(n('files_carried'), 'file')} (${formatBytes(n('file_bytes'))})`
            : 'files not included'}
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
      <p className="mt-3 text-xs text-fg-muted">
        To get this data back as it was, download the bundle and import it into
        a new project (Collections → Import bundle…).
      </p>
    </Card>
  )
}

function Verify({ name }: { name: string }) {
  const verify = useVerifyRelease(name)
  const r = verify.data
  return (
    <Card
      title="Check it"
      action={
        <Button
          size="sm"
          disabled={verify.isPending}
          onClick={() => verify.mutate()}
        >
          {verify.isPending ? 'Checking…' : 'Verify'}
        </Button>
      }
    >
      {verify.isPending ? (
        <p className="flex items-center gap-2 text-sm text-fg-muted">
          <Spinner /> Reading the bundle back…
        </p>
      ) : verify.error ? (
        <ErrorState message={errorMessage(verify.error)} />
      ) : r ? (
        r.matches ? (
          <p className="text-sm text-success" role="status">
            Intact: the bundle still holds exactly what the release was made
            with.
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
          Recompute the content hash from the stored bundle and compare.
        </p>
      )}
    </Card>
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
