import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { auditApi, type AuditEventQuery } from '../api/audit'
import { useToast } from '../components/ui/ToastProvider'
import { errorMessage } from '../lib/errors'
import { invalidateRecordNames } from './useRecordName'

/** What undoing a history entry would do, fetched only once it is asked for. */
export function useRevertPlan(entryId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['audit-revert-plan', entryId],
    queryFn: () => auditApi.revertPlan(entryId),
    enabled,
    // A plan describes the record as it is now, so never reuse an old one.
    gcTime: 0,
  })
}

/** Undo a history entry. Refreshes everything a record edit refreshes, since a
 * revert is one: the record, lists it appears in, its history and the trash. */
export function useRevertEntry(onDone?: () => void) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (vars: { id: string; force?: boolean }) =>
      auditApi.revert(vars.id, { force: vars.force }),
    onSuccess: (result) => {
      toast.success(
        result.kind === 'restore'
          ? 'Record restored'
          : result.kind === 'delete'
            ? 'Record deleted'
            : 'Change reverted',
      )
      onDone?.()
    },
    onError: (error) => toast.error(errorMessage(error)),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['record'] })
      qc.invalidateQueries({ queryKey: ['records'] })
      qc.invalidateQueries({ queryKey: ['record-audit'] })
      qc.invalidateQueries({ queryKey: ['audit'] })
      qc.invalidateQueries({ queryKey: ['trash'] })
      qc.invalidateQueries({ queryKey: ['records-deleted'] })
      qc.invalidateQueries({ queryKey: ['collections'] })
      invalidateRecordNames(qc)
    },
  })
}

/** The fields a history filter may test, from the server. */
export function useAuditFilterFields() {
  return useQuery({
    queryKey: ['audit', 'filter-fields'],
    queryFn: auditApi.filterFields,
    staleTime: Infinity,
  })
}

/** A page of history as events, for a filter, a search and an order. */
export function useAuditEvents(
  query: AuditEventQuery,
  page: number,
  size: number,
) {
  return useQuery({
    queryKey: ['audit', 'events', query, page, size],
    queryFn: () => auditApi.events(query, page * size, size),
    placeholderData: keepPreviousData,
  })
}

/** The changes in one batch, a page at a time. */
export function useBatchEntries(batchId: string, page: number, size: number) {
  return useQuery({
    queryKey: ['audit', 'batch', batchId, page, size],
    queryFn: () => auditApi.batchEntries(batchId, page * size, size),
    placeholderData: keepPreviousData,
  })
}

/** How history is stored. Read often while it is being converted (a bar moves),
 * rarely otherwise. */
export function useHistoryStorage() {
  return useQuery({
    queryKey: ['audit', 'storage'],
    queryFn: auditApi.storage,
    refetchInterval: (q) => (q.state.data?.converting ? 2000 : 60_000),
  })
}

export function useReclaimHistoryStorage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: auditApi.reclaimStorage,
    onSuccess: (storage) => qc.setQueryData(['audit', 'storage'], storage),
  })
}
