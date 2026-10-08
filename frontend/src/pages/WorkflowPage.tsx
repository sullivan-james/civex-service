import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { usePlugins } from '../hooks/usePlugins'
import { useLibrary, useLibraryItem, useRemoteStatus } from '../hooks/useRemote'
import { useDeleteWorkflow, useWorkflows } from '../hooks/useWorkflows'
import { errorMessage } from '../lib/errors'
import {
  sharingLabel,
  sharingState,
  workflowRows,
} from '../utils/workflowSharing'
import {
  Badge,
  Button,
  ConfirmDialog,
  ErrorState,
  Page,
  TabNav,
  TabPanel,
  useTabParam,
  type PageMenuAction,
} from '../components/ui'
import { LibraryInstallDialog } from '../components/workflows/LibraryInstallDialog'
import { PublishDialog } from '../components/workflows/PublishDialog'
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal'
import { WorkflowSharing } from '../components/workflows/WorkflowSharing'
import { WorkflowSummary } from '../components/workflows/WorkflowSummary'

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'sharing', label: 'Sharing' },
] as const
type TabId = (typeof TABS)[number]['id']

/** One workflow: what it does, and how it stands with the library (its
 * versions, publishing, installing). A workflow only in the library has a page
 * too, from which it is installed. */
export default function WorkflowPage() {
  const { stem = '' } = useParams()
  const navigate = useNavigate()
  const [tab, setTab] = useTabParam<TabId>(TABS, 'overview')
  const { data: local, isLoading, error } = useWorkflows()
  const { data: status } = useRemoteStatus()
  const sharing = !!status && (status.serving || !!status.remote)
  const { data: library = [] } = useLibrary()
  const { data: plugins = [] } = usePlugins()
  const deleteWf = useDeleteWorkflow()
  const [running, setRunning] = useState(false)
  const [installing, setInstalling] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteWarning, setDeleteWarning] = useState<string | null>(null)

  const row = workflowRows(local ?? [], sharing ? library : []).find(
    (r) => r.stem === stem,
  )
  const breadcrumbs = [{ label: 'Workflows', to: '/workflows' }]
  if (isLoading || !local) {
    return <Page breadcrumbs={breadcrumbs} loading="Loading…" />
  }
  if (error || !row) {
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={
          <ErrorState
            message={
              error
                ? errorMessage(error)
                : `There is no workflow '${stem}' here or in the library.`
            }
          />
        }
      />
    )
  }

  const state = sharingState(row)
  const badge = sharingLabel(row)
  const secondary: PageMenuAction[] = []
  if (row.local) {
    secondary.push({
      label: 'Edit',
      onClick: () => navigate(`/workflows/${encodeURIComponent(stem)}/edit`),
    })
    secondary.push({
      label: 'See its runs',
      onClick: () =>
        navigate(`/runs?workflow=${encodeURIComponent(row.local!.name)}`),
    })
    if (sharing && (state === 'not-shared' || state === 'changed')) {
      secondary.push({
        label: state === 'changed' ? 'Publish changes…' : 'Publish…',
        onClick: () => setPublishing(true),
      })
    }
    secondary.push({
      label: 'Delete…',
      variant: 'danger',
      onClick: () => {
        setDeleteWarning(null)
        setDeleting(true)
      },
    })
  }

  return (
    <Page
      breadcrumbs={[...breadcrumbs, { label: row.name }]}
      title={row.name}
      meta={
        <span className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-mono text-fg-muted">{stem}.yaml</span>
          {row.triggers.length === 0 ? (
            <span className="text-fg-muted">Runs by hand</span>
          ) : (
            row.triggers.map((t) => (
              <span key={t} className="text-fg-muted">
                Runs on {t}
              </span>
            ))
          )}
          {sharing && <Badge variant={badge.variant}>{badge.label}</Badge>}
        </span>
      }
      action={
        row.local ? (
          <Button variant="primary" onClick={() => setRunning(true)}>
            Run
          </Button>
        ) : (
          <Button variant="primary" onClick={() => setInstalling(true)}>
            Install…
          </Button>
        )
      }
      secondaryActions={secondary}
    >
      <TabNav label="Workflow" tabs={[...TABS]} value={tab} onChange={setTab} />
      <TabPanel id="overview" value={tab}>
        {row.local ? (
          <WorkflowSummary stem={stem} plugins={plugins} />
        ) : (
          <LibraryOverview stem={stem} />
        )}
      </TabPanel>
      <TabPanel id="sharing" value={tab}>
        <WorkflowSharing row={row} sharing={sharing} library={library} />
      </TabPanel>

      {running && row.local && (
        <WorkflowRunModal
          workflow={row.local}
          onClose={() => setRunning(false)}
        />
      )}
      {installing && (
        <LibraryInstallDialog
          kind="workflow"
          name={stem}
          onClose={() => setInstalling(false)}
        />
      )}
      {publishing && (
        <PublishDialog
          stem={stem}
          name={row.name}
          sharedVersion={row.shared?.version ?? null}
          onClose={() => setPublishing(false)}
        />
      )}
      {deleting && row.local && (
        <ConfirmDialog
          title="Delete workflow"
          body={`Delete workflow '${row.name}'? This cannot be undone. A copy in the library stays there.`}
          confirmLabel={deleteWarning ? 'Delete anyway' : 'Delete'}
          variant="danger"
          warning={deleteWarning}
          isPending={deleteWf.isPending}
          onClose={() => setDeleting(false)}
          onConfirm={async () => {
            try {
              await deleteWf.mutateAsync({
                stem,
                force: deleteWarning !== null,
              })
              navigate('/workflows', { replace: true })
            } catch (err) {
              setDeleteWarning(errorMessage(err))
            }
          }}
        />
      )}
    </Page>
  )
}

/** A workflow only in the library: what its newest version says. */
function LibraryOverview({ stem }: { stem: string }) {
  const { data, error } = useLibraryItem('workflow', stem)
  if (error) return <p className="text-danger">{errorMessage(error)}</p>
  if (!data) return <p className="text-fg-muted">Loading…</p>
  return (
    <div className="space-y-3 text-sm">
      {data.description && <p className="text-fg-muted">{data.description}</p>}
      <p>
        Not installed here. This is the newest version in the library (v
        {data.version}).
      </p>
      <pre className="max-h-[60vh] overflow-auto rounded bg-canvas-inset p-3 font-mono text-xs">
        {data.content}
      </pre>
    </div>
  )
}
