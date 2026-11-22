import { useState } from 'react'
import { useBatchRevertPlan, useRevertBatch } from '../../hooks/useAudit'
import {
  Button,
  Checkbox,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Spinner,
} from '../ui'

const n = (count: number) =>
  `${count.toLocaleString()} record${count === 1 ? '' : 's'}`

/** Undo a bulk edit as the one thing it was: every record it changed gets its
 * old values back, each judged as a single revert would judge it. Says what
 * happens before doing it. */
export function UndoEditDialog({
  batchId,
  onClose,
}: {
  batchId: string
  onClose: () => void
}) {
  const [force, setForce] = useState(false)
  const { data: plan, error, isLoading } = useBatchRevertPlan(batchId, force)
  const undo = useRevertBatch(onClose)
  const nothing = !!plan && plan.applied === 0

  return (
    <Modal onClose={onClose} size="md" dismissible={!undo.isPending}>
      <ModalHeader onClose={undo.isPending ? undefined : onClose}>
        Undo this edit
      </ModalHeader>
      <ModalBody className="space-y-3">
        {error ? (
          <p className="text-sm text-danger">
            Could not check what would be undone.
          </p>
        ) : isLoading || !plan ? (
          <Spinner />
        ) : (
          <>
            <p className="text-sm text-fg">
              {nothing
                ? 'Nothing in this edit can be undone now.'
                : `${n(plan.applied)} get their old values back.`}
              {plan.same > 0 && ` ${n(plan.same)} already have them.`}
            </p>
            {plan.conflicts > 0 && (
              <label className="flex items-center gap-2 text-sm text-fg">
                <Checkbox
                  checked={force}
                  onChange={(e) => setForce(e.target.checked)}
                />
                {n(plan.conflicts)} were edited again since. Put their old
                values back too
              </label>
            )}
            {plan.left > 0 && (
              <div className="space-y-1 text-sm text-fg-muted">
                <p>{n(plan.left)} stay as they are:</p>
                <ul className="list-disc pl-5">
                  {plan.reasons.slice(0, 5).map((r) => (
                    <li key={r.record_id}>{r.reason}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose} disabled={undo.isPending}>
          {nothing ? 'Close' : 'Cancel'}
        </Button>
        {!nothing && (
          <Button
            variant="primary"
            disabled={!plan || undo.isPending}
            onClick={() => undo.mutate({ batchId, force })}
          >
            {undo.isPending ? 'Undoing…' : 'Undo'}
          </Button>
        )}
      </ModalFooter>
    </Modal>
  )
}
