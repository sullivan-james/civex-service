import { useState } from 'react'
import { byWhom } from '../../utils/syncConflicts'
import type { AuditLogEntry, RevertField, RevertPlan } from '../../api/audit'
import { blockerTarget } from '../../api/restore'
import { useRevertEntry, useRevertPlan } from '../../hooks/useAudit'
import { RestoreDialog } from '../trash/RestoreDialog'
import { usePurgeItem } from '../trash/usePurgeItem'
import { errorMessage } from '../../lib/errors'
import { changeLabel } from '../../utils/auditValues'
import { AuditValue } from './AuditValue'
import {
  Badge,
  Button,
  Checkbox,
  ConfirmDialog,
  ErrorState,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Spinner,
} from '../ui'
import { AuditChangeList } from './AuditChanges'
import { EntrySubject } from './EntrySubject'
import { SyncOutcome } from './SyncOutcome'

const REVERTIBLE_ACTIONS = ['update', 'create']

/** Only edits and creations of records are undone from here: undoing a schema
 * change could destroy data, so that is left to a person editing the schema.
 * Undoing a delete is restoring, which has its own window. */
function canRevert(entry: AuditLogEntry): boolean {
  return (
    entry.entity_type === 'record' && REVERTIBLE_ACTIONS.includes(entry.action)
  )
}

/** One history entry in full, with Revert for a change to a record. */
export function AuditEntryDialog({
  entry,
  title,
  onClose,
}: {
  entry: AuditLogEntry
  title: string
  onClose: () => void
}) {
  const [reverting, setReverting] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [purging, setPurging] = useState(false)
  const purge = usePurgeItem()
  // A deletion of something that is still deleted can be undone, or made final.
  const now = entry.now
  const stillDeleted =
    entry.action === 'delete' && now?.status === 'deleted' && !!now.ref
  return (
    <Modal onClose={onClose} size="lg">
      <ModalHeader onClose={onClose}>{title}</ModalHeader>
      {reverting ? (
        <RevertPanel
          entry={entry}
          onBack={() => setReverting(false)}
          onDone={onClose}
        />
      ) : (
        <>
          <ModalBody className="space-y-3">
            <EntrySubject entry={entry} full />
            <p className="text-xs text-fg-muted">
              {new Date(entry.timestamp).toLocaleString()}
              {entry.actor ? ` · by ${byWhom(entry.actor, entry.device)}` : ''}
            </p>
            <SyncOutcome entry={entry} />
            <AuditChangeList changes={entry.changes} action={entry.action} />
          </ModalBody>
          <ModalFooter>
            <Button onClick={onClose}>Close</Button>
            {stillDeleted && now?.kind !== 'field' && (
              <Button variant="danger" onClick={() => setPurging(true)}>
                Delete permanently…
              </Button>
            )}
            {stillDeleted && (
              <Button variant="primary" onClick={() => setRestoring(true)}>
                Restore…
              </Button>
            )}
            {canRevert(entry) && (
              <Button variant="primary" onClick={() => setReverting(true)}>
                {entry.action === 'create' ? 'Delete record…' : 'Revert…'}
              </Button>
            )}
          </ModalFooter>
        </>
      )}
      {restoring && now?.ref && (
        <RestoreDialog
          target={{
            kind: now.kind,
            ref: now.ref,
            schema: now.schema_name ?? undefined,
          }}
          onClose={() => setRestoring(false)}
        />
      )}
      {purging && now?.ref && (
        <ConfirmDialog
          title="Delete permanently"
          body={`Permanently delete '${now.name ?? now.ref}'? This cannot be undone.`}
          confirmLabel="Delete permanently"
          variant="danger"
          onConfirm={() => {
            purge({ kind: now.kind, ref: now.ref! })
            setPurging(false)
            onClose()
          }}
          onClose={() => setPurging(false)}
        />
      )}
    </Modal>
  )
}

const STATUS: Record<
  RevertField['status'],
  { label: string; variant: 'success' | 'attention' | 'default' | 'danger' }
> = {
  apply: { label: 'Will be put back', variant: 'success' },
  conflict: { label: 'Edited since', variant: 'attention' },
  same: { label: 'Already as it was', variant: 'default' },
  skipped: { label: "Can't be put back", variant: 'danger' },
}

/** The step after Revert…: what would happen, and the button that does it.
 * The plan comes from the server, which is also what the revert itself
 * follows, so the preview can't say one thing and the revert do another. */
function RevertPanel({
  entry,
  onBack,
  onDone,
}: {
  entry: AuditLogEntry
  onBack: () => void
  onDone: () => void
}) {
  const { data: plan, isLoading, error } = useRevertPlan(entry.id, true)
  const [force, setForce] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const revert = useRevertEntry(onDone)

  if (isLoading || error || !plan)
    return (
      <>
        <ModalBody>
          {error ? <ErrorState message={errorMessage(error)} /> : <Spinner />}
        </ModalBody>
        <ModalFooter>
          <Button onClick={onBack}>Back</Button>
        </ModalFooter>
      </>
    )

  const willPutBack = plan.fields.filter(
    (f) => f.status === 'apply' || (force && f.status === 'conflict'),
  ).length
  const nothingToDo =
    plan.blocked != null ||
    (plan.kind === 'update' ? willPutBack === 0 : !plan.can_apply)

  return (
    <>
      <ModalBody className="space-y-4">
        <PlanSummary plan={plan} />
        {plan.blocker && (
          <Button onClick={() => setRestoring(true)}>
            Restore the {plan.blocker.kind} “{plan.blocker.name}”…
          </Button>
        )}
        {plan.kind === 'update' && <PlanFields fields={plan.fields} />}
        {plan.has_conflicts && (
          <label className="flex items-center gap-2 text-sm text-fg">
            <Checkbox
              checked={force}
              onChange={(e) => setForce(e.target.checked)}
              disabled={revert.isPending}
            />
            Also overwrite the fields edited since
          </label>
        )}
      </ModalBody>
      <ModalFooter>
        <Button onClick={onBack} disabled={revert.isPending}>
          Back
        </Button>
        <Button
          variant={plan.kind === 'delete' ? 'danger' : 'primary'}
          disabled={nothingToDo || revert.isPending}
          onClick={() => revert.mutate({ id: entry.id, force })}
        >
          {revert.isPending ? 'Working…' : confirmLabel(plan)}
        </Button>
      </ModalFooter>
      {restoring && plan.blocker && (
        <RestoreDialog
          target={blockerTarget(plan.blocker)}
          onClose={() => setRestoring(false)}
        />
      )}
    </>
  )
}

function confirmLabel(plan: RevertPlan): string {
  if (plan.kind === 'restore') return 'Restore record'
  if (plan.kind === 'delete') return 'Delete record'
  return 'Revert'
}

function PlanSummary({ plan }: { plan: RevertPlan }) {
  if (plan.blocked) return <p className="text-sm text-fg">{plan.blocked}</p>
  if (plan.kind === 'restore')
    return (
      <p className="text-sm text-fg">This brings the deleted record back.</p>
    )
  if (plan.kind === 'delete')
    return (
      <p className="text-sm text-fg">
        This deletes the record. It can be restored from Activity.
      </p>
    )
  if (!plan.fields.length)
    return (
      <p className="text-sm text-fg">This entry changed no field values.</p>
    )
  return null
}

function PlanFields({ fields }: { fields: RevertField[] }) {
  return (
    <ul className="divide-y divide-border rounded-md border border-border">
      {fields.map((f) => (
        <li key={f.field} className="space-y-1 px-3 py-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium text-fg">
              {changeLabel(f)}
            </span>
            <Badge variant={STATUS[f.status].variant}>
              {STATUS[f.status].label}
            </Badge>
          </div>
          <p className="text-sm text-fg break-words">
            <AuditValue value={f.current} dtype={f.dtype} compact /> →{' '}
            <AuditValue value={f.target} dtype={f.dtype} compact />
          </p>
          {f.reason && <p className="text-xs text-fg-muted">{f.reason}</p>}
        </li>
      ))}
    </ul>
  )
}
