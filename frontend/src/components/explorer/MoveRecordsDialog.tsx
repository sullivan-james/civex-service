import { useMemo, useState } from 'react'
import type { MoveRecordsRequest } from '../../api/records'
import type { RecordQueryParams } from '../../api/query'
import type { Schema } from '../../api/schemas'
import { useCollections } from '../../hooks/useCollections'
import { useMovePlan, useMoveRecords } from '../../hooks/useRecords'
import { errorMessage } from '../../lib/errors'
import { pluralise } from '../../lib/utils'
import {
  Button,
  Field,
  FormError,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Select,
  Spinner,
} from '../ui'
import { RecordSearchPicker } from '../records/RecordSearchPicker'

/** The records to move: the rows ticked, or everything the list's query shows. */
export type MoveSelection =
  { ids: string[] } | { query: RecordQueryParams; collection: string }

/** Move the chosen records to another collection, or inside another record
 * there, after the server says what that does (how many go, with everything
 * beneath them) and whether anything is in the way. One dialog for a ticked
 * selection and for "all N matching"; the plan is asked again as the choices
 * change, and Move is only offered when it can be done. */
export function MoveRecordsDialog({
  selection,
  count,
  listed,
  schemas,
  from,
  onClose,
  onMoved,
}: {
  selection: MoveSelection
  /** How many records are chosen, for the title. */
  count: number
  /** The kind of record listed: decides whether they need a record to go inside. */
  listed: Schema
  schemas: Schema[]
  /** The collection the list shows. */
  from: string
  onClose: () => void
  onMoved: () => void
}) {
  const { data: collections } = useCollections()
  const live = useMemo(
    () => (collections ?? []).filter((c) => !c.deleted_at),
    [collections],
  )
  const holder = listed.parent_id
    ? schemas.find((s) => s.id === listed.parent_id)
    : undefined
  // Another collection by default (once the list has arrived): that is what
  // the dialog is for. Within the same one, a record can still be moved
  // inside another record.
  const [to, setTo] = useState<string | null>(null)
  const [parent, setParent] = useState<string | undefined>()
  const move = useMoveRecords()

  // Nothing is asked until the collections are known: the default is one of
  // them, and a plan for the wrong one would flash by.
  const target = collections
    ? (to ?? live.find((c) => c.name !== from)?.name ?? from)
    : null
  const body: MoveRecordsRequest | null =
    target && (!holder || parent)
      ? {
          to: target,
          parent: parent ?? null,
          ...('ids' in selection
            ? { ids: selection.ids }
            : {
                collection: selection.collection,
                schema_name: selection.query.schema ?? null,
                within: selection.query.within ?? null,
                filter: selection.query.filter ?? null,
                where: selection.query.where ?? [],
                search: selection.query.search ?? null,
              }),
        }
      : null
  const plan = useMovePlan(body)
  const kind = listed.label ?? listed.name
  const canMove = !!plan.data?.can_move && !move.isPending

  function confirm() {
    if (!body) return
    move.mutate(body, {
      onSuccess: () => {
        onMoved()
        onClose()
      },
    })
  }

  return (
    <Modal onClose={onClose} size="md" dismissible={!move.isPending}>
      <ModalHeader onClose={move.isPending ? undefined : onClose}>
        Move {pluralise(count, kind.toLowerCase())}
      </ModalHeader>
      <ModalBody>
        <div className="space-y-4">
          <Field
            label="To collection"
            info="Each record goes with everything inside it and keeps its id, values and history. Its files stay where they are stored."
          >
            <Select
              aria-label="To collection"
              value={target ?? ''}
              onChange={(e) => {
                setTo(e.target.value)
                setParent(undefined)
              }}
            >
              {live.map((c) => (
                <option key={c.id} value={c.name}>
                  {c.name}
                  {c.name === from ? ' (here)' : ''}
                </option>
              ))}
            </Select>
          </Field>
          {holder && (
            <Field
              label={`Inside which ${holder.label ?? holder.name}`}
              required
              info={`A ${kind} sits inside a ${holder.label ?? holder.name}: choose the one in ${target} it goes in.`}
            >
              <RecordSearchPicker
                key={target}
                schemaName={holder.name}
                collection={target ?? undefined}
                value={parent ?? undefined}
                onChange={setParent}
                required
                aria-label={`Inside which ${holder.label ?? holder.name}`}
                placeholder={`Search ${holder.label ?? holder.name} records in ${target}…`}
              />
            </Field>
          )}
          <PlanText
            loading={plan.isLoading || (plan.isFetching && !plan.data)}
            error={plan.error}
            waiting={!body}
            plan={plan.data}
          />
          <FormError message={move.error ? errorMessage(move.error) : null} />
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose} disabled={move.isPending}>
          Cancel
        </Button>
        <Button onClick={confirm} disabled={!canMove}>
          {move.isPending
            ? 'Moving…'
            : plan.data?.records
              ? `Move ${plan.data.records.toLocaleString()}`
              : 'Move'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}

function PlanText({
  loading,
  error,
  waiting,
  plan,
}: {
  loading: boolean
  error: unknown
  waiting: boolean
  plan: ReturnType<typeof useMovePlan>['data']
}) {
  if (waiting)
    return (
      <p className="text-sm text-fg-muted">
        Choose where the records go to see what the move would do.
      </p>
    )
  if (error) return <FormError message={errorMessage(error)} />
  if (loading || !plan)
    return (
      <p className="flex items-center gap-2 text-sm text-fg-muted">
        <Spinner /> Working out what would move…
      </p>
    )
  const where = plan.parent_name
    ? `inside “${plan.parent_name}” in ${plan.collection}`
    : plan.collection
  return (
    <div className="space-y-2 text-sm" data-testid="move-plan">
      {plan.records > 0 ? (
        <p>
          {pluralise(plan.records, 'record')} would move to {where}
          {plan.records > plan.roots
            ? ` (${pluralise(plan.roots, 'chosen record')} with everything inside)`
            : ''}
          {plan.sources.length
            ? ` from ${plan.sources.map((s) => `“${s}”`).join(', ')}`
            : ''}
          .
        </p>
      ) : (
        <p className="text-fg-muted">
          Nothing would move: the chosen records are already there.
        </p>
      )}
      {plan.skipped > 0 && plan.records > 0 && (
        <p className="text-fg-muted">
          {pluralise(plan.skipped, 'record')} already there, left as{' '}
          {plan.skipped === 1 ? 'it is' : 'they are'}.
        </p>
      )}
      {plan.problems.map((p) => (
        <p key={p} className="text-danger" role="alert">
          {p}
        </p>
      ))}
    </div>
  )
}
