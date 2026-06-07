import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { datasetsApi } from '../api/datasets'

export function useDatasets() {
  return useQuery({ queryKey: ['datasets'], queryFn: datasetsApi.list })
}

export function useDataset(name: string) {
  return useQuery({ queryKey: ['datasets', name], queryFn: () => datasetsApi.get(name), enabled: !!name })
}

export function useCreateDataset() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: datasetsApi.create,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['datasets'] }),
  })
}

export function useDeleteDataset() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: datasetsApi.delete,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['datasets'] }),
  })
}
