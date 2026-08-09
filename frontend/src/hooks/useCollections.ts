import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { collectionsApi } from '../api/collections'
import { useToast } from '../components/ui/ToastProvider'
import { errorMessage } from '../lib/errors'

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
  const toast = useToast()
  return useMutation({
    mutationFn: collectionsApi.create,
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['collections'] })
      toast.success(`Collection "${created.name}" created`)
    },
  })
}

export function useUpdateCollection() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: ({
      name,
      body,
    }: {
      name: string
      body: { rename?: string; description?: string }
    }) => collectionsApi.update(name, body),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['collections'] })
      toast.success(`Collection "${updated.name}" updated`)
    },
  })
}

export function useDeleteCollection() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: collectionsApi.delete,
    onSuccess: (_data, collectionName) => {
      qc.invalidateQueries({ queryKey: ['collections'] })
      toast.success(`Collection "${collectionName}" deleted`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}
