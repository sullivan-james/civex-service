import { useState } from 'react'
import {
  blockerTarget,
  type RestorePlan,
  type RestoreTarget,
} from '../../api/restore'
import { useRestore, useRestorePlan } from '../../hooks/useRestore'
import { errorMessage } from '../../lib/errors'
import {
  Button,
  ErrorState,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Spinner,
} from '../ui'

const KIND_WORD = {
  record: 'record',
  collection: 'collection',
  schema: 'schema',
}

const records = (n: number) =>
  `${n.toLocaleString()} record${n === 1 ? '' : 's'}`

/** Restore one deleted thing, after saying what that does. When something
 * above it is still deleted, offers to restore that instead (and what was
 * deleted with it), so a record never comes back somewhere it can't be seen. */
export function RestoreDialog({
  target,
  onClose,
}: {
  target: RestoreTarget
  onClose: () => void
}) {
  // Following a blocker pushes it; Back pops.
  const [trail, setTrail] = useState<RestoreTarget[]>([target])
  const current = trail[trail.length - 1]
  const { data: plan, error, isLoading } = useRestorePlan(current)
  const restore = useRestore(onClose)

  return (
    <Modal onClose={onClose} size="md" dismissible={!restore.isPending}>
      <ModalHeader onClose={restore.isPending ? undefined : onClose}>
        Restore {plan ? `“${plan.name}”` : ''}
      </ModalHeader>
      {error || isLoading || !plan ? (
        <>
          <ModalBody>
            {error ? <ErrorState message={errorMessage(error)} /> : <Spinner />}
          </ModalBody>
          <ModalFooter>
            <Button onClick={onClose}>Close</Button>
          </ModalFooter>
        </>
      ) : (
        <>
          <ModalBody className="space-y-3">
            <PlanBody plan={plan} />
          </ModalBody>
          <ModalFooter>
            {trail.length > 1 ? (
              <Button
                onClick={() => setTrail(trail.slice(0, -1))}
                disabled={restore.isPending}
              >
                Back
              </Button>
            ) : (
              <Button onClick={onClose} disabled={restore.isPending}>
                Cancel
              </Button>
            )}
            {plan.blocked_by ? (
              <Button
                variant="primary"
                onClick={() =>
                  setTrail([...trail, blockerTarget(plan.blocked_by!)])
                }
              >
                Restore the {KIND_WORD[plan.blocked_by.kind]} “
                {plan.blocked_by.name}” instead…
              </Button>
            ) : (
              <Button
                variant="primary"
                disabled={restore.isPending}
                onClick={() => restore.mutate(plan)}
              >
                {restore.isPending ? 'Restoring…' : 'Restore'}
              </Button>
            )}
          </ModalFooter>
        </>
      )}
    </Modal>
  )
}

function PlanBody({ plan }: { plan: RestorePlan }) {
  if (plan.blocked_by)
    return (
      <>
        <p className="text-sm text-fg">{plan.blocked}</p>
        <p className="text-sm text-fg-muted">
          Restoring it also brings back what was deleted with it, and this
          record can then be restored.
        </p>
      </>
    )
  if (plan.kind === 'record')
    return (
      <p className="text-sm text-fg">
        “{plan.name}” goes back to {plan.collection ?? 'its collection'}
        {plan.records > 1
          ? `, along with ${records(plan.records - 1)} deleted with it.`
          : '.'}
      </p>
    )
  return (
    <p className="text-sm text-fg">
      The {KIND_WORD[plan.kind]} “{plan.name}” comes back
      {plan.records > 0
        ? `, with the ${records(plan.records)} deleted with it.`
        : '.'}{' '}
      {plan.records > 0 && 'Records deleted separately earlier stay deleted.'}
    </p>
  )
}
