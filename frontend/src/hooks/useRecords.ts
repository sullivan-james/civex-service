import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { recordsApi, type ListParams } from '../api/records'
import { useToast } from '../components/ui/ToastProvider'
import { errorMessage } from '../lib/errors'

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

export function useRecordCounts(datasetName: string) {
  return useQuery({
    queryKey: ['record-counts', datasetName],
    queryFn: () => recordsApi.counts(datasetName),
    enabled: !!datasetName,
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
    refetchInterval: refetchInterval ?? false,
  })
}

export function useCreateRecord(datasetName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (body: Parameters<typeof recordsApi.create>[1]) =>
      recordsApi.create(datasetName, body),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['records', datasetName] })
      qc.invalidateQueries({ queryKey: ['record-counts', datasetName] })
      qc.invalidateQueries({ queryKey: ['collections'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
      toast.success(`Record "${created.natural_name ?? created.id}" created`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

export function useUpdateRecord() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: object }) =>
      recordsApi.update(id, { data }),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['record', updated.id] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
      toast.success(`Record "${updated.natural_name ?? updated.id}" updated`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

export function useDeleteRecord(datasetName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: recordsApi.delete,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['records', datasetName] })
      qc.invalidateQueries({ queryKey: ['record-counts', datasetName] })
      qc.invalidateQueries({ queryKey: ['collections'] })
      toast.success('Record deleted')
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

export function useDeleteAllRecords(datasetName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (schema?: string) => recordsApi.deleteAll(datasetName, schema),
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
