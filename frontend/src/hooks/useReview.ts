import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { reviewApi, type ReviewStatus } from '../api/review'
import { selectionBody, type RecordSelection } from '../api/records'

/** What a review or a note changes: the record (its status, its count of open
 * notes), every list it is in, its notes and history. */
function useRefresh() {
  const qc = useQueryClient()
  return (recordId?: string) => {
    qc.invalidateQueries({ queryKey: ['records'] })
    qc.invalidateQueries({ queryKey: ['audit'] })
    if (recordId) {
      qc.invalidateQueries({ queryKey: ['record', recordId] })
      qc.invalidateQueries({ queryKey: ['notes', recordId] })
    } else {
      qc.invalidateQueries({ queryKey: ['record'] })
    }
  }
}

/** A record's notes, oldest first, resolved ones too. */
export function useNotes(recordId: string | null | undefined) {
  return useQuery({
    queryKey: ['notes', recordId],
    queryFn: () => reviewApi.notes(recordId!),
    enabled: !!recordId,
  })
}

/** Mark records (a selection, or one record by id) as needing a check,
 * checked, or not reviewed. */
export function useSetReview() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: ({
      selection,
      status,
    }: {
      selection: RecordSelection
      status: ReviewStatus
    }) => reviewApi.setReview({ ...selectionBody(selection), status }),
    onSuccess: (_, { selection }) =>
      refresh(
        'ids' in selection && selection.ids.length === 1
          ? selection.ids[0]
          : undefined,
      ),
  })
}

/** Add, change, resolve, reopen or delete a record's notes. */
export function useNoteActions(recordId: string) {
  const refresh = useRefresh()
  const done = { onSuccess: () => refresh(recordId) }
  return {
    add: useMutation({
      mutationFn: (body: string) => reviewApi.addNote(recordId, body),
      ...done,
    }),
    edit: useMutation({
      mutationFn: ({ id, body }: { id: string; body: string }) =>
        reviewApi.editNote(id, body),
      ...done,
    }),
    resolve: useMutation({
      mutationFn: ({ id, resolved }: { id: string; resolved: boolean }) =>
        reviewApi.resolveNote(id, resolved),
      ...done,
    }),
    remove: useMutation({
      mutationFn: (id: string) => reviewApi.deleteNote(id),
      ...done,
    }),
    restore: useMutation({
      mutationFn: (id: string) => reviewApi.restoreNote(id),
      ...done,
    }),
  }
}
