import { useState } from 'react'
import type { Note } from '../../api/notes'
import { useNoteActions, useNotes } from '../../hooks/useNotes'
import { useAccount, usePermissions } from '../../hooks/useMe'
import { formatDateTime } from '../../utils/dates'
import { openNotesHref, openNotesInsideHref } from '../../utils/notes'
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

/** A record's notes, as threads: each note that starts one, its replies
 * under it, oldest first, with who and when, and a Reply box. Resolve (or
 * Reopen) is on the thread; Edit is on a note or reply its author wrote;
 * Delete on each (deleting the first note hides its replies with it). Anyone
 * who may write records in the collection may add, reply, resolve and
 * delete. */
export function NotesPanel({
  recordId,
  collectionId,
}: {
  recordId: string
  collectionId: string
}) {
  const { data: threads, isLoading, error } = useNotes(recordId)
  const actions = useNoteActions(recordId)
  const { can, why } = usePermissions()
  const me = useAccount().name
  const mayWrite = can('write_records', collectionId)
  const refusal = mayWrite ? undefined : why('write_records')
  const [draft, setDraft] = useState('')
  const [replies, setReplies] = useState<Record<string, string>>({})
  const [editing, setEditing] = useState<{ id: string; body: string } | null>(
    null,
  )
  const [deleting, setDeleting] = useState<Note | null>(null)

  if (isLoading) return <Skeleton className="h-24 w-full" />
  if (error) return <ErrorState message={errorMessage(error)} />

  const open = (threads ?? []).filter((n) => !n.resolved_at)
  const resolved = (threads ?? []).filter((n) => n.resolved_at)

  function add() {
    actions.add.mutate(draft, { onSuccess: () => setDraft('') })
  }

  function reply(thread: Note) {
    actions.reply.mutate(
      { id: thread.id, body: replies[thread.id] ?? '' },
      { onSuccess: () => setReplies((r) => ({ ...r, [thread.id]: '' })) },
    )
  }

  /** One note or reply: who, when, what it says, Edit for its author and
   * Delete. */
  function entry(note: Note) {
    const isEditing = editing?.id === note.id
    return (
      <div key={note.id}>
        <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-fg-muted">
          <span className="font-medium text-fg">
            {note.author ?? 'Someone'}
          </span>
          <span>{formatDateTime(note.created_at)}</span>
          {note.edited_at && (
            <span title={formatDateTime(note.edited_at)}>(edited)</span>
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
          <div className="mt-1 flex flex-wrap gap-2">
            {note.author === me && (
              <Button
                size="sm"
                variant="ghost"
                disabled={!mayWrite}
                title={refusal}
                onClick={() => setEditing({ id: note.id, body: note.body })}
              >
                Edit
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              disabled={!mayWrite}
              title={refusal}
              onClick={() => setDeleting(note)}
            >
              Delete
            </Button>
          </div>
        )}
      </div>
    )
  }

  function thread(note: Note) {
    const text = replies[note.id] ?? ''
    return (
      <Card key={note.id} className={note.resolved_at ? 'opacity-70' : ''}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">{entry(note)}</div>
          <div className="flex shrink-0 items-center gap-2">
            {note.resolved_at && (
              <Badge variant="success">
                Resolved{note.resolved_by ? ` by ${note.resolved_by}` : ''}
              </Badge>
            )}
            <Button
              size="sm"
              disabled={!mayWrite || actions.resolve.isPending}
              title={refusal}
              onClick={() =>
                actions.resolve.mutate({
                  id: note.id,
                  resolved: !note.resolved_at,
                })
              }
            >
              {note.resolved_at ? 'Reopen' : 'Resolve'}
            </Button>
          </div>
        </div>
        {note.replies.length > 0 && (
          <div className="mt-3 space-y-3 border-l-2 border-border-muted pl-3">
            {note.replies.map(entry)}
          </div>
        )}
        {mayWrite && (
          <div className="mt-3 flex items-end gap-2 pl-3">
            <Textarea
              aria-label="Reply"
              placeholder={
                note.resolved_at ? 'Reply (opens the thread again)…' : 'Reply…'
              }
              value={text}
              maxLength={MAX_LENGTH}
              rows={1}
              className="w-full"
              onChange={(e) =>
                setReplies((r) => ({ ...r, [note.id]: e.target.value }))
              }
            />
            <Button
              size="sm"
              disabled={!text.trim() || actions.reply.isPending}
              onClick={() => reply(note)}
            >
              Reply
            </Button>
          </div>
        )}
      </Card>
    )
  }

  const failed =
    actions.add.error ?? actions.resolve.error ?? actions.reply.error ?? null

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
        <div className="flex items-center justify-between gap-2">
          <Button
            size="sm"
            variant="primary"
            disabled={!mayWrite || !draft.trim() || actions.add.isPending}
            title={refusal}
            onClick={add}
          >
            {actions.add.isPending ? 'Adding…' : 'Add note'}
          </Button>
          <span className="flex items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              to={openNotesInsideHref(collectionId, recordId)}
            >
              Open notes inside
            </Button>
            <Button size="sm" variant="ghost" to={openNotesHref()}>
              All open notes
            </Button>
          </span>
        </div>
        <FormError message={failed ? errorMessage(failed) : null} />
      </div>
      {(threads ?? []).length === 0 ? (
        <EmptyState
          title="No notes yet"
          message="Notes left here are seen by everyone working on this project."
        />
      ) : (
        <div className="space-y-2">
          {open.map(thread)}
          {resolved.length > 0 && (
            <>
              <p className="pt-2 text-xs font-medium text-fg-muted">Resolved</p>
              {resolved.map(thread)}
            </>
          )}
        </div>
      )}
      {deleting && (
        <ConfirmDialog
          title={deleting.thread_id ? 'Delete reply' : 'Delete note'}
          body={
            deleting.thread_id
              ? "Delete this reply? It stays in the record's history."
              : deleting.replies.length > 0
                ? "Delete this note and its replies? They stay in the record's history, and restoring the note brings them back."
                : "Delete this note? It stays in the record's history."
          }
          confirmLabel={deleting.thread_id ? 'Delete reply' : 'Delete note'}
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
