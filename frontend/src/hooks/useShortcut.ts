import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { settingsApi } from '../api/settings'

export function useShortcut() {
  return useQuery({
    queryKey: ['settings', 'shortcut'],
    queryFn: settingsApi.getShortcut,
    staleTime: 60_000,
  })
}

export function useCreateShortcut() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: settingsApi.createShortcut,
    onSuccess: (state) => qc.setQueryData(['settings', 'shortcut'], state),
  })
}
