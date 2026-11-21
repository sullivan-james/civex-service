import { useState } from 'react'
import type { Note } from '../../api/review'
import { useNoteActions, useNotes } from '../../hooks/useReview'
import { useAccount, usePermissions } from '../../hooks/useMe'
import { formatDateTime } from '../../utils/dates'
import { errorMessage } from '../../lib/errors'
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  FormError,
  Skeleton,
  Textarea,
} from '../ui'

const MAX_LENGTH = 4000

/** A record's notes: what people left on it ("value looks off, re-check the
 * calibration"), oldest first, with who and when; a box to add one; and on
 * each, Resolve (or Reopen), Edit for its author, and Delete. Anyone who may
 * write records in the collection may add, resolve and delete. */
export function NotesPanel({
  recordId,
  collectionId,
}: {
  recordId: string
  collectionId: string
}) {
  const { data: notes, isLoading, error } = useNotes(recordId)
  const actions = useNoteActions(recordId)
  const { can, why } = usePermissions()
  const me = useAccount().name
  const mayWrite = can('write_records', collectionId)
  const [draft, setDraft] = useState('')
  const [editing, setEditing] = useState<{ id: string; body: string } | null>(
    null,
  )
  const [deleting, setDeleting] = useState<Note | null>(null)

  if (isLoading) return <Skeleton className="h-24 w-full" />
  if (error) return <ErrorState message={errorMessage(error)} />

  const open = (notes ?? []).filter((n) => !n.resolved_at)
  const resolved = (notes ?? []).filter((n) => n.resolved_at)

  function add() {
    actions.add.mutate(draft, { onSuccess: () => setDraft('') })
  }

  function row(note: Note) {
    const mine = note.author === me
    const isEditing = editing?.id === note.id
    return (
      <Card key={note.id} className={note.resolved_at ? 'opacity-70' : ''}>
        <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-fg-muted">
          <span className="font-medium text-fg">
            {note.author ?? 'Someone'}
          </span>
          <span>{formatDateTime(note.created_at)}</span>
          {note.edited_at && (
            <span title={formatDateTime(note.edited_at)}>(edited)</span>
          )}
          {note.resolved_at && (
            <Badge variant="success">
              Resolved{note.resolved_by ? ` by ${note.resolved_by}` : ''}
            </Badge>
          )}
        </div>
        {isEditing ? (
          <div className="mt-2 space-y-2">
            <Textarea
              aria-label="Note"
              value={editing.body}
              maxLength={MAX_LENGTH}
              rows={3}
              className="w-full"
              onChange={(e) =>
                setEditing({ id: note.id, body: e.target.value })
              }
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="primary"
                disabled={!editing.body.trim() || actions.edit.isPending}
                onClick={() =>
                  actions.edit.mutate(editing, {
                    onSuccess: () => setEditing(null),
                  })
                }
              >
                Save
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(null)}
              >
                Cancel
              </Button>
            </div>
            <FormError
              message={
                actions.edit.error ? errorMessage(actions.edit.error) : null
              }
            />
          </div>
        ) : (
          <p className="mt-1 whitespace-pre-wrap text-sm">{note.body}</p>
        )}
        {!isEditing && (
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={!mayWrite || actions.resolve.isPending}
              title={mayWrite ? undefined : why('write_records')}
              onClick={() =>
                actions.resolve.mutate({
                  id: note.id,
                  resolved: !note.resolved_at,
                })
              }
            >
              {note.resolved_at ? 'Reopen' : 'Resolve'}
            </Button>
            {mine && (
              <Button
                size="sm"
                variant="ghost"
                disabled={!mayWrite}
                title={mayWrite ? undefined : why('write_records')}
                onClick={() => setEditing({ id: note.id, body: note.body })}
              >
                Edit
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              disabled={!mayWrite}
              title={mayWrite ? undefined : why('write_records')}
              onClick={() => setDeleting(note)}
            >
              Delete
            </Button>
          </div>
        )}
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Textarea
          aria-label="New note"
          placeholder={
            mayWrite
              ? 'Leave a note: what to check, what you found…'
              : why('write_records')
          }
          value={draft}
          maxLength={MAX_LENGTH}
          rows={3}
          className="w-full"
          disabled={!mayWrite}
          onChange={(e) => setDraft(e.target.value)}
        />
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="primary"
            disabled={!mayWrite || !draft.trim() || actions.add.isPending}
            title={mayWrite ? undefined : why('write_records')}
            onClick={add}
          >
            {actions.add.isPending ? 'Adding…' : 'Add note'}
          </Button>
        </div>
        <FormError
          message={
            actions.add.error || actions.resolve.error
              ? errorMessage(actions.add.error ?? actions.resolve.error)
              : null
          }
        />
      </div>
      {(notes ?? []).length === 0 ? (
        <EmptyState
          title="No notes yet"
          message="Notes left here are seen by everyone working on this project."
        />
      ) : (
        <div className="space-y-2">
          {open.map(row)}
          {resolved.length > 0 && (
            <>
              <p className="pt-2 text-xs font-medium text-fg-muted">Resolved</p>
              {resolved.map(row)}
            </>
          )}
        </div>
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete note"
          body="Delete this note? It stays in the record's history."
          confirmLabel="Delete note"
          variant="danger"
          isPending={actions.remove.isPending}
          warning={
            actions.remove.error
              ? errorMessage(actions.remove.error)
              : undefined
          }
          onConfirm={() =>
            actions.remove.mutate(deleting.id, {
              onSuccess: () => setDeleting(null),
            })
          }
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  )
}
