import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { collectionsApi } from '../api/collections'

export function useCollections() {
  return useQuery({ queryKey: ['collections'], queryFn: collectionsApi.list })
}

export function useCollection(name: string) {
  return useQuery({
    queryKey: ['collections', name],
    queryFn: () => collectionsApi.get(name),
    enabled: !!name,
  })
}

export function useCreateCollection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: collectionsApi.create,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['collections'] }),
  })
}

export function useUpdateCollection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      name,
      body,
    }: {
      name: string
      body: { rename?: string; description?: string }
    }) => collectionsApi.update(name, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['collections'] }),
  })
}

export function useDeleteCollection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: collectionsApi.delete,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['collections'] }),
  })
}
