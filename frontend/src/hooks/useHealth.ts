import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { healthApi } from '../api/health'
import { errorMessage } from '../lib/errors'
import { useToast } from '../components/ui/ToastProvider'

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: healthApi.check,
    // A check can take a while on a big project: run it when asked.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
}

export function useRepair() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: healthApi.repair,
    onSuccess: (result) => {
      qc.setQueryData(['health'], result.health)
      toast.success('Repaired. A backup was kept.')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
}
