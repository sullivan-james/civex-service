import { useQuery } from '@tanstack/react-query'
import { legalApi } from '../api/legal'

export function useLicense() {
  return useQuery({
    queryKey: ['legal', 'license'],
    queryFn: legalApi.getLicense,
    staleTime: Infinity,
  })
}

export function usePolicies() {
  return useQuery({
    queryKey: ['legal', 'policies'],
    queryFn: legalApi.listPolicies,
  })
}
