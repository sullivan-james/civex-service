import {
  keepPreviousData,
  useQuery,
  useMutation,
  useQueryClient,
  type QueryClient,
  type QueryKey,
} from '@tanstack/react-query'
import { useCallback } from 'react'
import {
  recordsApi,
  type CivexRecord,
  type FileSaver,
  type FileUpload,
  type PaginatedRecords,
  type ListParams,
  type MoveRecordsRequest,
} from '../api/records'
import type { RecordQueryParams } from '../api/query'
import { ApiError } from '../api/client'
import { useToast } from '../components/ui/ToastProvider'
import { errorMessage } from '../lib/errors'
import { invalidateRecordNames } from './useRecordName'

/**
 * Applies `updater` to every cached record matching `recordId` — the single
 * `['record', id]` query and any `['records', ...]` list page that
 * contains it — so an edit shows up everywhere without a round-trip.
 * Returns a snapshot for rollback in onError.
 */
function optimisticUpdateRecord(
  qc: QueryClient,
  recordId: string,
  updater: (record: CivexRecord) => CivexRecord,
): Map<QueryKey, unknown> {
  const previous = new Map<QueryKey, unknown>()
  for (const [key, data] of qc.getQueriesData<CivexRecord>({
    queryKey: ['record', recordId],
  })) {
    if (!data) continue
    previous.set(key, data)
    qc.setQueryData(key, updater(data))
  }
  for (const [key, data] of qc.getQueriesData<PaginatedRecords>({
    queryKey: ['records'],
  })) {
    if (!data?.items?.some((r) => r.id === recordId)) continue
    previous.set(key, data)
    qc.setQueryData(key, {
      ...data,
      items: data.items.map((r) => (r.id === recordId ? updater(r) : r)),
    })
  }
  return previous
}

function rollbackRecordCache(
  qc: QueryClient,
  previous: Map<QueryKey, unknown> | undefined,
) {
  previous?.forEach((data, key) => qc.setQueryData(key, data))
}

export function useRecords(
  datasetName: string,
  params?: ListParams,
  refetchInterval?: number | false,
) {
  return useQuery({
    queryKey: ['records', datasetName, params],
    queryFn: () => recordsApi.list(datasetName, params),
    enabled: !!datasetName,
    refetchInterval: refetchInterval ?? false,
  })
}

/** Whether *any* record of this schema exists, anywhere — not scoped to a
 * collection (schemas aren't dataset-scoped; the same schema's records can
 * live in different collections). Used for "is there a parent to pick from
 * yet" checks that need an answer before a collection is necessarily known
 * (e.g. the import wizard entered from a schema page). Mirrors
 * `RecordSearchPicker`'s own global `searchBySchema` call, just without a
 * search term and capped to 1 result. */
export function useHasSchemaRecords(schemaName: string | null | undefined) {
  const { data } = useQuery({
    queryKey: ['records-exist', schemaName],
    queryFn: () => recordsApi.searchBySchema(schemaName!, undefined, 1),
    enabled: !!schemaName,
  })
  return (data?.length ?? 0) > 0
}

/** One page of records -- of a collection, or (no `datasetName`, a
 * `schemaName`) of a schema across every collection. The same query either
 * way, so the explorer doesn't care which it is browsing. */
export function useRecordPage(
  scope: { datasetName?: string; schemaName?: string },
  params: ListParams,
  options: { enabled?: boolean; refetchInterval?: number | false } = {},
) {
  return useQuery({
    queryKey: ['records', scope.datasetName ?? null, scope.schemaName, params],
    queryFn: () =>
      scope.datasetName
        ? recordsApi.list(scope.datasetName, params)
        : recordsApi.listBySchema(scope.schemaName!, params),
    enabled:
      (options.enabled ?? true) && !!(scope.datasetName || scope.schemaName),
    refetchInterval: options.refetchInterval ?? false,
    placeholderData: keepPreviousData,
  })
}

/** Matching records per schema (optionally scoped to one record's
 * descendants via `params.within`). */
/** Records per schema in a collection; `null` counts every collection, and
 * '' waits (the collection isn't known yet). */
export function useRecordCounts(
  datasetName: string | null,
  params?: RecordQueryParams,
) {
  return useQuery({
    queryKey: ['record-counts', datasetName, params ?? null],
    queryFn: () => recordsApi.counts(datasetName ?? '', params),
    enabled: datasetName !== '',
  })
}

export function useRecord(
  id: string | null | undefined,
  refetchInterval?: number | false,
) {
  return useQuery({
    queryKey: ['record', id],
    queryFn: () => recordsApi.get(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      const error = query.state.error
      // Confirmed gone -- polling on a schedule won't make it reappear,
      // so stop instead of re-requesting (and re-retrying) it forever.
      if (error instanceof ApiError && error.status === 404) return false
      return refetchInterval ?? false
    },
  })
}

/** Under `records` so any record edit refreshes the counts. */
export function useReferrers(id: string) {
  return useQuery({
    queryKey: ['records', 'referrers', id],
    queryFn: () => recordsApi.referrers(id),
  })
}

type CreateBody = Parameters<typeof recordsApi.create>[1]

/** Creates a record; with `files` (chosen before it existed), the record and
 * its files go as one request, kept together or not at all. */
export function useCreateRecord(datasetName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: ({ files, ...body }: CreateBody & { files?: FileUpload[] }) =>
      files?.length
        ? recordsApi.createWithFiles(datasetName, body, files)
        : recordsApi.create(datasetName, body),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['records', datasetName] })
      qc.invalidateQueries({ queryKey: ['record-counts', datasetName] })
      qc.invalidateQueries({ queryKey: ['collections'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
      // A file attached changes what the drives hold.
      qc.invalidateQueries({ queryKey: ['store', 'volumes'] })
      qc.invalidateQueries({ queryKey: ['store', 'collection'] })
      toast.success(`Record "${created.natural_name ?? created.id}" created`)
    },
  })
}

/** `quiet` suppresses the success/failure toasts, for callers (inline cell
 * editing) that show the outcome next to the thing edited instead. */
export function useUpdateRecord({ quiet = false }: { quiet?: boolean } = {}) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: object }) =>
      recordsApi.update(id, { data }),
    onMutate: async ({ id, data }) => {
      await qc.cancelQueries({ queryKey: ['record', id] })
      await qc.cancelQueries({ queryKey: ['records'] })
      const previous = optimisticUpdateRecord(qc, id, (r) => ({
        ...r,
        // The PATCH body is the record's full data (the API replaces, it
        // doesn't merge), so mirror that -- merging would leave a cleared
        // field showing its old value until the refetch.
        data: data as Record<string, unknown>,
      }))
      return { previous }
    },
    onError: (err, _vars, context) => {
      rollbackRecordCache(qc, context?.previous)
      if (quiet) return
      toast.error(
        `Couldn't save record changes — reverted. ${errorMessage(err)}`,
      )
    },
    onSuccess: (updated) => {
      if (quiet) return
      toast.success(`Record "${updated.natural_name ?? updated.id}" updated`)
    },
    onSettled: (_data, _err, vars) => settleRecordCaches(qc, vars.id),
  })
}

/** Everything a saved record may have changed on screen: the record, the
 * lists (its natural name, reference labels in rows), its history, what the
 * drives hold, and the runs it may have started. */
function settleRecordCaches(qc: QueryClient, id: string) {
  qc.invalidateQueries({ queryKey: ['record', id] })
  qc.invalidateQueries({ queryKey: ['records'] })
  qc.invalidateQueries({ queryKey: ['record-audit', id] })
  qc.invalidateQueries({ queryKey: ['store', 'volumes'] })
  qc.invalidateQueries({ queryKey: ['store', 'collection'] })
  qc.invalidateQueries({ queryKey: ['jobs'] })
  invalidateRecordNames(qc)
}

/** The record page's `FileSaver`: a file chosen in a field is stored and the
 * record saved with it as one request (`recordsApi.attachFile`), the answer
 * shown at once and the caches settled as after any save. */
export function useRecordFileSaver(recordId: string): FileSaver {
  const qc = useQueryClient()
  return useCallback<FileSaver>(
    async (field, file, onProgress, signal) => {
      const record = await recordsApi.attachFile(
        recordId,
        field.name,
        file,
        onProgress,
        signal,
      )
      qc.setQueryData(['record', recordId], record)
      settleRecordCaches(qc, recordId)
      return record
    },
    [qc, recordId],
  )
}

export function useDeleteRecord(datasetName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (vars: { id: string; undo?: () => Promise<unknown> }) =>
      recordsApi.delete(vars.id),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['records', datasetName] })
      qc.invalidateQueries({ queryKey: ['record-counts', datasetName] })
      qc.invalidateQueries({ queryKey: ['collections'] })
      qc.invalidateQueries({ queryKey: ['records-deleted'] })
      qc.invalidateQueries({ queryKey: ['trash'] })
      invalidateRecordNames(qc)
      qc.invalidateQueries({ queryKey: ['record-audit', vars.id] })
      toast.success('Record moved to Recently Deleted', {
        action: vars.undo
          ? {
              label: 'Undo',
              onClick: () => {
                vars.undo!().then(
                  () => {
                    qc.invalidateQueries({ queryKey: ['records', datasetName] })
                    qc.invalidateQueries({
                      queryKey: ['record-counts', datasetName],
                    })
                    qc.invalidateQueries({ queryKey: ['collections'] })
                    qc.invalidateQueries({ queryKey: ['records-deleted'] })
                    qc.invalidateQueries({ queryKey: ['trash'] })
                    invalidateRecordNames(qc)
                    toast.success('Record restored')
                  },
                  (err) => toast.error(errorMessage(err)),
                )
              },
            }
          : undefined,
      })
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

export function useDeletedRecords(datasetName?: string) {
  return useQuery({
    queryKey: ['records-deleted', datasetName],
    queryFn: () => recordsApi.listDeleted(datasetName),
  })
}

export function usePurgeRecord() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: recordsApi.purge,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['records-deleted'] })
      qc.invalidateQueries({ queryKey: ['trash'] })
      invalidateRecordNames(qc)
      toast.success('Record permanently deleted')
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

export function useDeleteManyRecords(datasetName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (ids: string[]) => recordsApi.deleteMany(ids),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['records', datasetName] })
      qc.invalidateQueries({ queryKey: ['record-counts', datasetName] })
      qc.invalidateQueries({ queryKey: ['collections'] })
      toast.success(
        `${result.deleted} record${result.deleted === 1 ? '' : 's'} deleted`,
      )
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

/** Deletes everything `params` matches -- "select all N matching". */
export function useDeleteMatchingRecords(datasetName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (params: RecordQueryParams) =>
      recordsApi.deleteMatching(datasetName, params),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['records', datasetName] })
      qc.invalidateQueries({ queryKey: ['record-counts', datasetName] })
      qc.invalidateQueries({ queryKey: ['collections'] })
      toast.success(
        `${result.deleted} record${result.deleted === 1 ? '' : 's'} deleted`,
      )
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

/** What a move would do, worked out by the server as the choices change;
 * nothing is asked while `body` is null (the choices are incomplete). */
export function useMovePlan(body: MoveRecordsRequest | null) {
  return useQuery({
    queryKey: ['record-move-plan', body],
    queryFn: () => recordsApi.movePlan(body!),
    enabled: body !== null,
    placeholderData: keepPreviousData,
  })
}

/** Moves records to another collection (or inside another record). Every
 * list of records may have changed: the ones they left, the ones they
 * joined, and the counts of both. */
export function useMoveRecords() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (body: MoveRecordsRequest) => recordsApi.move(body),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['records'] })
      qc.invalidateQueries({ queryKey: ['record'] })
      qc.invalidateQueries({ queryKey: ['record-counts'] })
      qc.invalidateQueries({ queryKey: ['collections'] })
      qc.invalidateQueries({ queryKey: ['record-move-plan'] })
      toast.success(
        `${result.records} record${result.records === 1 ? '' : 's'} moved to ${result.collection}`,
      )
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}
