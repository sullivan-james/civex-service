import { Link } from 'react-router'
import type { RetentionReport, RetentionRequest } from '../../api/retention'
import { useRetentionPreview, useRunRetention } from '../../hooks/useRetention'
import { errorMessage } from '../../lib/errors'
import {
  ConfirmDialog,
  ErrorState,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Spinner,
  Button,
} from '../ui'

const n = (count: number, one: string, many = `${one}s`) =>
  `${count.toLocaleString()} ${count === 1 ? one : many}`

/** What the report removes, in plain words: one line per kind that has any. */
function Lines({ report }: { report: RetentionReport }) {
  const lines: string[] = []
  if (
    report.deleted_records ||
    report.deleted_collections ||
    report.deleted_schemas
  )
    lines.push(
      `Deleted items removed for good: ${[
        report.deleted_collections &&
          n(report.deleted_collections, 'collection'),
        report.deleted_schemas && n(report.deleted_schemas, 'schema'),
        report.deleted_records && n(report.deleted_records, 'record'),
      ]
        .filter(Boolean)
        .join(', ')}.`,
    )
  if (report.audit_entries)
    lines.push(
      `Change history removed: ${n(report.audit_entries, 'entry', 'entries')}.`,
    )
  if (report.runs)
    lines.push(
      `Workflow runs removed: ${n(report.runs, 'run')}, with ${n(report.run_steps, 'step log')}.`,
    )
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm text-fg">
      {lines.map((l) => (
        <li key={l}>{l}</li>
      ))}
    </ul>
  )
}

function Kept({ report }: { report: RetentionReport }) {
  return (
    <div className="space-y-1 text-xs text-fg-muted">
      {report.audit_kept_restorable > 0 && (
        <p>
          {n(
            report.audit_kept_restorable,
            'older history entry',
            'older history entries',
          )}{' '}
          kept: they are about things that can still be restored.
        </p>
      )}
      {report.audit_kept_unsynced > 0 && (
        <p>
          {n(
            report.audit_kept_unsynced,
            'older history entry',
            'older history entries',
          )}{' '}
          kept: not yet synced.
        </p>
      )}
      {report.skipped.map((s) => (
        <p key={s} className="text-attention">
          Could not delete {s}
        </p>
      ))}
    </div>
  )
}

/** Count what a clean-up would remove, then remove it only after it has been
 * read and "delete" typed. Nothing is removed by looking. */
export function RetentionCleanUpDialog({
  request,
  onClose,
}: {
  request: RetentionRequest
  onClose: () => void
}) {
  const { data: report, error, isLoading } = useRetentionPreview(request)
  const run = useRunRetention(onClose)

  if (error || isLoading || !report)
    return (
      <Modal onClose={onClose} size="md">
        <ModalHeader onClose={onClose}>Clean up</ModalHeader>
        <ModalBody>
          {error ? <ErrorState message={errorMessage(error)} /> : <Spinner />}
        </ModalBody>
        <ModalFooter>
          <Button onClick={onClose}>Close</Button>
        </ModalFooter>
      </Modal>
    )

  if (!report.anything)
    return (
      <Modal onClose={onClose} size="md">
        <ModalHeader onClose={onClose}>Nothing to clean up</ModalHeader>
        <ModalBody className="space-y-3">
          <p className="text-sm text-fg">Nothing is old enough to remove.</p>
          <Kept report={report} />
        </ModalBody>
        <ModalFooter>
          <Button onClick={onClose}>Close</Button>
        </ModalFooter>
      </Modal>
    )

  return (
    <ConfirmDialog
      title="Delete for good"
      body={
        <div className="space-y-3">
          <Lines report={report} />
          <Kept report={report} />
          <p className="text-sm text-fg-muted">
            This cannot be undone. Files nothing refers to afterwards are
            removed by{' '}
            <Link
              to="/settings/storage?tab=tasks"
              className="text-accent hover:underline"
            >
              Clean up unused files
            </Link>
            .
          </p>
        </div>
      }
      confirmLabel="Delete for good"
      variant="danger"
      typedConfirmationValue="delete"
      isPending={run.isPending}
      onConfirm={() => run.mutate(request)}
      onClose={onClose}
    />
  )
}
