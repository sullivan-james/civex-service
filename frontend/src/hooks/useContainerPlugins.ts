import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { containerPluginsApi } from '../api/containerPlugins'

export function useContainerPlugins() {
  return useQuery({
    queryKey: ['containerPlugins'],
    queryFn: containerPluginsApi.list,
    staleTime: 30_000,
  })
}

export function useContainerPlugin(name: string) {
  return useQuery({
    queryKey: ['containerPlugins', name],
    queryFn: () => containerPluginsApi.get(name),
    enabled: !!name,
  })
}

export function useSaveContainerPluginFile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      name,
      path,
      content,
    }: {
      name: string
      path: string
      content: string
    }) => containerPluginsApi.saveFile(name, path, content),
    onSuccess: (_result, { name }) => {
      qc.invalidateQueries({ queryKey: ['containerPlugins', name] })
      qc.invalidateQueries({ queryKey: ['containerPlugins'] })
    },
  })
}
