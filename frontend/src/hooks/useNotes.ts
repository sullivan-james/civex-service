import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { notesApi } from '../api/notes'

/** What a note changes: the record (its count of open threads), every list
 * it is in, its notes and history. */
function useRefresh() {
  const qc = useQueryClient()
  return (recordId: string) => {
    qc.invalidateQueries({ queryKey: ['records'] })
    qc.invalidateQueries({ queryKey: ['audit'] })
    qc.invalidateQueries({ queryKey: ['record', recordId] })
    qc.invalidateQueries({ queryKey: ['notes', recordId] })
  }
}

/** A record's threads, oldest first, resolved ones too, each with its
 * replies. */
export function useNotes(recordId: string | null | undefined) {
  return useQuery({
    queryKey: ['notes', recordId],
    queryFn: () => notesApi.notes(recordId!),
    enabled: !!recordId,
  })
}

/** Add, reply to, change, resolve, reopen or delete a record's notes. */
export function useNoteActions(recordId: string) {
  const refresh = useRefresh()
  const done = { onSuccess: () => refresh(recordId) }
  return {
    add: useMutation({
      mutationFn: (body: string) => notesApi.addNote(recordId, body),
      ...done,
    }),
    reply: useMutation({
      mutationFn: ({ id, body }: { id: string; body: string }) =>
        notesApi.reply(id, body),
      ...done,
    }),
    edit: useMutation({
      mutationFn: ({ id, body }: { id: string; body: string }) =>
        notesApi.editNote(id, body),
      ...done,
    }),
    resolve: useMutation({
      mutationFn: ({ id, resolved }: { id: string; resolved: boolean }) =>
        notesApi.resolveNote(id, resolved),
      ...done,
    }),
    remove: useMutation({
      mutationFn: (id: string) => notesApi.deleteNote(id),
      ...done,
    }),
    restore: useMutation({
      mutationFn: (id: string) => notesApi.restoreNote(id),
      ...done,
    }),
  }
}
