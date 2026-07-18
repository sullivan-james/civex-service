import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { recordsApi, type ListParams } from '../api/records'

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
  return useMutation({
    mutationFn: (body: Parameters<typeof recordsApi.create>[1]) =>
      recordsApi.create(datasetName, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['records', datasetName] })
      qc.invalidateQueries({ queryKey: ['record-counts', datasetName] })
      qc.invalidateQueries({ queryKey: ['collections'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

export function useUpdateRecord() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: object }) =>
      recordsApi.update(id, { data }),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['record', updated.id] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

export function useDeleteRecord(datasetName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: recordsApi.delete,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['records', datasetName] })
      qc.invalidateQueries({ queryKey: ['record-counts', datasetName] })
      qc.invalidateQueries({ queryKey: ['collections'] })
    },
  })
}

export function useDeleteManyRecords(datasetName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) => recordsApi.deleteMany(ids),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['records', datasetName] })
      qc.invalidateQueries({ queryKey: ['record-counts', datasetName] })
      qc.invalidateQueries({ queryKey: ['collections'] })
    },
  })
}

export function useDeleteAllRecords(datasetName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (schema?: string) => recordsApi.deleteAll(datasetName, schema),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['records', datasetName] })
      qc.invalidateQueries({ queryKey: ['record-counts', datasetName] })
      qc.invalidateQueries({ queryKey: ['collections'] })
    },
  })
}
