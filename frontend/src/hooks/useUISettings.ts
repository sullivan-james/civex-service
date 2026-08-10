import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { settingsApi } from '../api/settings'

export function useUISettings() {
  return useQuery({
    queryKey: ['settings', 'ui'],
    queryFn: settingsApi.getUi,
    staleTime: 30_000,
  })
}

export function useSetShowAdvanced() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (showAdvanced: boolean) => settingsApi.updateUi(showAdvanced),
    onSuccess: (settings) => qc.setQueryData(['settings', 'ui'], settings),
  })
}
