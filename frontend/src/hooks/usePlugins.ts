import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { pluginsApi } from '../api/plugins'

export function usePlugins() {
  return useQuery({
    queryKey: ['plugins'],
    queryFn: pluginsApi.list,
    staleTime: 30_000,
  })
}

export function usePluginLoadErrors() {
  return useQuery({
    queryKey: ['plugins', 'errors'],
    queryFn: pluginsApi.loadErrors,
    staleTime: 30_000,
  })
}

export function usePluginSource(filename: string) {
  return useQuery({
    queryKey: ['plugins', filename, 'source'],
    queryFn: () => pluginsApi.source(filename),
    enabled: !!filename,
  })
}

export function useSavePlugin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, code }: { name: string; code: string }) =>
      pluginsApi.save(name, code),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plugins'] }),
  })
}

export function useUploadPlugin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => pluginsApi.upload(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plugins'] }),
  })
}

export function useDeletePlugin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ filename, force }: { filename: string; force?: boolean }) =>
      pluginsApi.delete(filename, force),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plugins'] }),
  })
}
