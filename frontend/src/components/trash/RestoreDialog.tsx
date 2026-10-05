import { useState } from 'react'
import {
  blockerTarget,
  type RestoreKind,
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

const KIND_WORD: Record<RestoreKind, string> = {
  record: 'record',
  collection: 'collection',
  schema: 'schema',
  field: 'field',
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
  const parents = plan?.parents_needed ?? 0
  // Whether the clash is in the record itself (nothing to do but change or
  // delete the other record) or only in something deleted with it, in which
  // case restoring just this record still works.
  const clashHere = plan?.conflict?.record_id === plan?.id
  const blockedByRecords =
    plan?.blocked_by?.kind === 'record' && plan.parents_needed != null

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
              <>
                {blockedByRecords && (
                  <>
                    <Button
                      disabled={restore.isPending}
                      onClick={() =>
                        restore.mutate({
                          ...plan,
                          onlyThis: true,
                          withParents: true,
                        })
                      }
                    >
                      {restore.isPending
                        ? 'Restoring…'
                        : `Restore only this (${records(parents + 1)})`}
                    </Button>
                    {plan.records > 1 && (
                      <Button
                        disabled={restore.isPending}
                        onClick={() =>
                          restore.mutate({ ...plan, withParents: true })
                        }
                      >
                        {`This and the ${records(plan.records - 1)} deleted with it (${records(parents + plan.records)})`}
                      </Button>
                    )}
                  </>
                )}
                <Button
                  variant="primary"
                  onClick={() =>
                    setTrail([...trail, blockerTarget(plan.blocked_by!)])
                  }
                >
                  Restore the {KIND_WORD[plan.blocked_by.kind]} “
                  {plan.blocked_by.name}” and all of it…
                </Button>
              </>
            ) : plan.kind === 'record' && plan.records > 1 ? (
              <>
                {plan.conflict && (
                  <Button
                    variant="link"
                    to={`/records/${plan.conflict.existing_id}`}
                    onClick={onClose}
                  >
                    Open “{plan.conflict.existing_name}”
                  </Button>
                )}
                <Button
                  disabled={restore.isPending || (!!plan.conflict && clashHere)}
                  onClick={() => restore.mutate({ ...plan, onlyThis: true })}
                >
                  Restore only this
                </Button>
                <Button
                  variant="primary"
                  disabled={restore.isPending || !plan.can_restore}
                  onClick={() => restore.mutate(plan)}
                >
                  {restore.isPending
                    ? 'Restoring…'
                    : `Restore with the ${records(plan.records - 1)} deleted with it`}
                </Button>
              </>
            ) : (
              <>
                {plan.conflict && (
                  <Button
                    variant="primary"
                    to={`/records/${plan.conflict.existing_id}`}
                    onClick={onClose}
                  >
                    Open “{plan.conflict.existing_name}”
                  </Button>
                )}
                <Button
                  variant={plan.conflict ? undefined : 'primary'}
                  disabled={restore.isPending || !plan.can_restore}
                  onClick={() => restore.mutate(plan)}
                >
                  {restore.isPending ? 'Restoring…' : 'Restore'}
                </Button>
              </>
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
          {plan.blocked_by.kind === 'record' && plan.parents_needed != null
            ? `Restoring it brings back everything that was deleted with it. Or bring back just this ${KIND_WORD[plan.kind]}, with the ${records(plan.parents_needed)} it sits under (each by itself), and leave the rest deleted.`
            : `Restoring it also brings back everything that was deleted with it, and this ${KIND_WORD[plan.kind]} can then be restored.`}
        </p>
      </>
    )
  if (plan.conflict)
    return (
      <>
        <p className="text-sm text-fg">{plan.conflict.message}</p>
        {plan.conflict.record_id !== plan.id && (
          <p className="text-sm text-fg-muted">
            The clash is with “{plan.conflict.record_name}”, deleted with it.
            You can still bring back just “{plan.name}”, and leave that one
            deleted.
          </p>
        )}
      </>
    )
  // Nothing deleted above it is the cause (a field whose name was taken), so
  // restoring something else won't help; the message says what will.
  if (plan.blocked) return <p className="text-sm text-fg">{plan.blocked}</p>
  if (plan.kind === 'field')
    return (
      <p className="text-sm text-fg">
        The field “{plan.name}” comes back on the schema “{plan.schema_name}”,
        with the values records still hold for it.
      </p>
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
