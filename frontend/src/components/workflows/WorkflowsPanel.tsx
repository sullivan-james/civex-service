import { useState } from 'react'
import { useWorkflows, useDeleteWorkflow } from '../../hooks/useWorkflows'
import {
  DataTable,
  type DataTableColumn,
  Button,
  ConfirmDialog,
} from '../ui'
import type { Workflow } from '../../api/workflows'

interface WorkflowsPanelProps {
  onRun: (workflow: Workflow) => void
  onEdit: (workflow: Workflow) => void
}

export function WorkflowsPanel({ onRun, onEdit }: WorkflowsPanelProps) {
  const { data: workflows, isLoading, error } = useWorkflows()
  const deleteWf = useDeleteWorkflow()

  const [deleteTarget, setDeleteTarget] = useState<Workflow | null>(null)
  const [deleteWarning, setDeleteWarning] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  function openDelete(wf: Workflow) {
    setDeleteError(null)
    setDeleteWarning(null)
    setDeleteTarget(wf)
  }

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

  const columns: DataTableColumn<Workflow>[] = [
    {
      key: 'name',
      header: 'Name',
      render: (wf) => <span className="font-medium text-fg">{wf.name}</span>,
    },
    {
      key: 'description',
      header: 'Description',
      render: (wf) => (
        <span className="text-fg-muted">{wf.description ?? '—'}</span>
      ),
    },
    {
      key: 'steps',
      header: 'Steps',
      align: 'right',
      width: '80px',
      render: (wf) => <span className="text-fg-muted">{wf.steps}</span>,
    },
    {
      key: 'filename',
      header: 'File',
      render: (wf) => (
        <span className="font-mono text-xs text-fg-muted">{wf.filename}</span>
      ),
    },
  ]

  return (
    <>
      {deleteError && <p className="text-xs text-danger mb-2">{deleteError}</p>}
      <DataTable
        columns={columns}
        rows={workflows ?? []}
        getRowId={(wf) => wf.stem}
        isLoading={isLoading}
        error={error?.message}
        emptyTitle="No workflows yet"
        emptyMessage="Workflows automate data processing — they run when records are created or updated. Create a .yaml file in .civex/workflows/ to get started."
        actions={(wf) => (
          <div className="flex justify-end gap-2">
            <Button size="sm" onClick={() => onRun(wf)}>
              Run
            </Button>
            <Button size="sm" variant="default" onClick={() => onEdit(wf)}>
              Edit
            </Button>
            <Button size="sm" variant="danger" onClick={() => openDelete(wf)}>
              Delete
            </Button>
          </div>
        )}
        actionsLabel="Actions"
        actionsWidth="200px"
      />

      {deleteTarget && (
        <ConfirmDialog
          title="Delete workflow"
          body={`Delete workflow '${deleteTarget.name}'? This cannot be undone.`}
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
    </>
  )
}
