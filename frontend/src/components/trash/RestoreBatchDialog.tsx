import { useRestoreAll, useRestoreAllPlan } from '../../hooks/useRestore'
import {
  Button,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Spinner,
} from '../ui'

const n = (count: number, word: string) =>
  `${count.toLocaleString()} ${word}${count === 1 ? '' : 's'}`

/** Undo a bulk delete as the one thing it was: a record and everything beneath
 * it (or whatever else that one delete took) comes back together, parent
 * first, without finding each part. Says what comes back before doing it. */
export function RestoreBatchDialog({
  batchId,
  onClose,
  onChoose,
}: {
  batchId: string
  onClose: () => void
  /** Open the delete's contents to pick which records to bring back, instead
   * of all of them. */
  onChoose?: () => void
}) {
  const {
    data: plan,
    error,
    isLoading,
  } = useRestoreAllPlan({ batch: batchId }, true)
  const restore = useRestoreAll(onClose)
  const nothing = !!plan && plan.things === 0

  return (
    <Modal onClose={onClose} size="md" dismissible={!restore.isPending}>
      <ModalHeader onClose={restore.isPending ? undefined : onClose}>
        Restore everything this delete took
      </ModalHeader>
      <ModalBody className="space-y-3">
        {error ? (
          <p className="text-sm text-danger">
            Could not check what would come back.
          </p>
        ) : isLoading || !plan ? (
          <Spinner />
        ) : nothing ? (
          <p className="text-sm text-fg">
            Nothing from this delete is still deleted.
          </p>
        ) : (
          <>
            <p className="text-sm text-fg">
              {[
                plan.collections > 0 && n(plan.collections, 'collection'),
                plan.schemas > 0 && n(plan.schemas, 'schema'),
                plan.fields > 0 && n(plan.fields, 'field'),
                plan.records > 0 && n(plan.records, 'record'),
              ]
                .filter(Boolean)
                .join(', ')}{' '}
              come back, {n(plan.restores, 'record')} in all, with the parent
              first so everything lands where it was.
            </p>
            {plan.blocked > 0 && (
              <p className="text-sm text-fg-muted">
                {plan.blocked.toLocaleString()} stay deleted: something they
                belong to is deleted and was not part of this delete.
              </p>
            )}
          </>
        )}
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose} disabled={restore.isPending}>
          {nothing ? 'Close' : 'Cancel'}
        </Button>
        {!nothing && onChoose && (
          <Button onClick={onChoose} disabled={restore.isPending}>
            Choose which…
          </Button>
        )}
        {!nothing && (
          <Button
            variant="primary"
            disabled={!plan || restore.isPending}
            onClick={() => restore.mutate({ batch: batchId })}
          >
            {restore.isPending ? 'Restoring…' : 'Restore all'}
          </Button>
        )}
      </ModalFooter>
    </Modal>
  )
}
