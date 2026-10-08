import { useState } from 'react'
import { useNavigate } from 'react-router'
import type { Workflow } from '../../api/workflows'
import { useListParams } from '../../hooks/useListParams'
import { useLibrary, useRemoteStatus } from '../../hooks/useRemote'
import { useDeleteWorkflow, useWorkflows } from '../../hooks/useWorkflows'
import { errorMessage } from '../../lib/errors'
import {
  SHOW_OPTIONS,
  sharingLabel,
  sharingState,
  shows,
  workflowHref,
  workflowRows,
  type WorkflowRow,
} from '../../utils/workflowSharing'
import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  IconButton,
  ListToolbar,
  Menu,
  Pagination,
  type DataTableColumn,
  type MenuItem,
} from '../ui'
import { MoreVertical } from '../ui/icons'
import { LibraryInstallDialog } from './LibraryInstallDialog'
import { PublishDialog } from './PublishDialog'

interface WorkflowsPanelProps {
  onRun: (workflow: Workflow) => void
  /** Only show workflows triggered by this schema's records (`record_schema`),
   * and not those only in the library. Omit for the full list (the Workflows
   * page). */
  schemaName?: string
  /** Prefix for the list's address parameters, when the page has others. */
  ns?: string
}

/** Every workflow in this project and, while it shares with a server, every
 * one in the library, in one list: searchable, filterable by how each stands
 * with the library, and each a page of its own. Sharing is a row's actions,
 * not a separate place. */
export function WorkflowsPanel({
  onRun,
  schemaName,
  ns = '',
}: WorkflowsPanelProps) {
  const navigate = useNavigate()
  const { data: local, isLoading, error } = useWorkflows()
  const { data: status } = useRemoteStatus()
  const sharing = !!status && (status.serving || !!status.remote)
  const { data: library, error: libraryError } = useLibrary()
  const list = useListParams(ns, ['show'])
  const deleteWf = useDeleteWorkflow()

  const [installing, setInstalling] = useState<WorkflowRow | null>(null)
  const [publishing, setPublishing] = useState<WorkflowRow | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Workflow | null>(null)
  const [deleteWarning, setDeleteWarning] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const all = workflowRows(local ?? [], sharing ? (library ?? []) : []).filter(
    (r) =>
      !schemaName || (r.local !== null && r.local.record_schema === schemaName),
  )
  const wanted = list.q.trim().toLowerCase()
  const matching = all.filter(
    (r) =>
      shows(r, list.picks.show) &&
      (!wanted ||
        `${r.name} ${r.stem} ${r.description ?? ''} ${r.triggers.join(' ')}`
          .toLowerCase()
          .includes(wanted)),
  )
  const dir = list.sort?.dir === 'desc' ? -1 : 1
  const sorted = [...matching].sort((a, b) =>
    list.sort?.field === 'steps'
      ? dir * ((a.steps ?? -1) - (b.steps ?? -1))
      : list.sort?.field === 'sharing'
        ? dir * sharingLabel(a).label.localeCompare(sharingLabel(b).label)
        : dir * a.name.localeCompare(b.name),
  )
  const shown = sorted.slice(list.page * list.size, (list.page + 1) * list.size)
  const filtered = !!wanted || !!list.picks.show

  async function confirmDelete() {
    if (!deleteTarget) return
    try {
      await deleteWf.mutateAsync({
        stem: deleteTarget.stem,
        force: deleteWarning !== null,
      })
      setDeleteTarget(null)
      setDeleteWarning(null)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Delete failed'
      if (deleteWarning === null) {
        setDeleteWarning(message)
      } else {
        setDeleteError(message)
        setDeleteTarget(null)
        setDeleteWarning(null)
      }
    }
  }

  function menuFor(row: WorkflowRow): MenuItem[] {
    const state = sharingState(row)
    const items: MenuItem[] = []
    if (row.local) {
      items.push({
        label: 'Edit',
        onClick: () => navigate(`${workflowHref(row.stem)}/edit`),
      })
    }
    if (
      sharing &&
      row.local &&
      (state === 'not-shared' || state === 'changed')
    ) {
      items.push({
        label: state === 'changed' ? 'Publish changes…' : 'Publish…',
        onClick: () => setPublishing(row),
      })
    }
    if (state === 'update') {
      items.push({
        label: `Update to v${row.shared?.version}…`,
        onClick: () => setInstalling(row),
      })
    }
    if (row.shared) {
      items.push({
        label: 'Versions…',
        onClick: () => navigate(`${workflowHref(row.stem)}?tab=sharing`),
      })
    }
    if (row.local) {
      const wf = row.local
      items.push({
        label: 'Delete…',
        variant: 'danger',
        onClick: () => {
          setDeleteError(null)
          setDeleteWarning(null)
          setDeleteTarget(wf)
        },
      })
    }
    return items
  }

  const columns: DataTableColumn<WorkflowRow>[] = [
    {
      key: 'name',
      header: 'Name',
      sortable: true,
      render: (r) => (
        <span className="flex flex-col">
          <span className="font-medium text-fg">{r.name}</span>
          {r.description && (
            <span className="text-xs text-fg-muted">{r.description}</span>
          )}
        </span>
      ),
    },
    {
      key: 'runs',
      header: 'Runs by itself',
      render: (r) =>
        r.triggers.length === 0 ? (
          <span className="text-fg-muted">By hand</span>
        ) : (
          <span className="text-xs">
            {r.triggers.map((t) => (
              <span key={t} className="block">
                {t}
              </span>
            ))}
          </span>
        ),
    },
    {
      key: 'steps',
      header: 'Steps',
      align: 'right',
      width: '80px',
      sortable: true,
      render: (r) => <span className="text-fg-muted">{r.steps ?? '—'}</span>,
    },
    ...(sharing
      ? [
          {
            key: 'sharing',
            header: 'Sharing',
            sortable: true,
            render: (r: WorkflowRow) => {
              const { label, variant } = sharingLabel(r)
              return <Badge variant={variant}>{label}</Badge>
            },
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-3">
      <ListToolbar
        search={{
          value: list.q,
          label: 'Search workflows',
          onChange: (q) => list.set({ q }),
        }}
        picks={
          sharing
            ? [
                {
                  label: 'Show…',
                  value: list.picks.show,
                  options: schemaName
                    ? SHOW_OPTIONS.filter((o) => o.value !== 'library')
                    : SHOW_OPTIONS,
                  onChange: (show) => list.set({ show }),
                },
              ]
            : []
        }
      />
      {libraryError && sharing && (
        <p role="alert" className="text-xs text-danger">
          The library can't be read: {errorMessage(libraryError)}
        </p>
      )}
      {deleteError && <p className="text-xs text-danger">{deleteError}</p>}
      <DataTable
        dense
        layout="auto"
        columns={columns}
        rows={shown}
        getRowId={(r) => r.stem}
        rowHref={(r) => workflowHref(r.stem)}
        isLoading={isLoading}
        error={error?.message}
        sort={
          list.sort
            ? { key: list.sort.field, direction: list.sort.dir }
            : undefined
        }
        onSortChange={list.toggleSort}
        emptyTitle={
          filtered
            ? 'No workflows match'
            : schemaName
              ? 'No automations for this record type yet'
              : 'No workflows yet'
        }
        emptyMessage={
          filtered
            ? 'Try a different search or choice.'
            : schemaName
              ? 'Automations run when a record of this type is created or updated: set one up from an import, or write a new workflow.'
              : 'Workflows run when records are created or updated, or by hand.'
        }
        actions={(r) => (
          <span className="inline-flex items-center justify-end gap-1">
            {r.local ? (
              <Button size="sm" onClick={() => onRun(r.local!)}>
                Run
              </Button>
            ) : (
              <Button size="sm" onClick={() => setInstalling(r)}>
                Install…
              </Button>
            )}
            {menuFor(r).length > 0 && (
              <Menu
                items={menuFor(r)}
                trigger={({ open, toggle }) => (
                  <IconButton
                    icon={MoreVertical}
                    aria-label={`More for ${r.name}`}
                    onClick={toggle}
                    aria-expanded={open}
                    aria-haspopup="menu"
                  />
                )}
              />
            )}
          </span>
        )}
        actionsLabel="Actions"
        actionsWidth="140px"
      />
      <Pagination
        page={list.page}
        pageSize={list.size}
        total={matching.length}
        onPage={(page) => list.set({ page })}
        onPageSize={(size) => list.set({ size })}
      />

      {installing && (
        <LibraryInstallDialog
          kind="workflow"
          name={installing.stem}
          onClose={() => setInstalling(null)}
        />
      )}
      {publishing && (
        <PublishDialog
          stem={publishing.stem}
          name={publishing.name}
          sharedVersion={publishing.shared?.version ?? null}
          onClose={() => setPublishing(null)}
        />
      )}
      {deleteTarget && (
        <ConfirmDialog
          title="Delete workflow"
          body={`Delete workflow '${deleteTarget.name}'? This cannot be undone. A copy in the library stays there.`}
          confirmLabel={deleteWarning ? 'Delete anyway' : 'Delete'}
          variant="danger"
          warning={deleteWarning}
          isPending={deleteWf.isPending}
          onConfirm={confirmDelete}
          onClose={() => {
            setDeleteTarget(null)
            setDeleteWarning(null)
          }}
        />
      )}
    </div>
  )
}
