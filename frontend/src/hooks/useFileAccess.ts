import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fileAccessApi } from '../api/fileAccess'

const EXPORTS = ['file-access', 'exports']

/** The export folders civex made, newest first. */
export function useExports() {
  return useQuery({
    queryKey: EXPORTS,
    queryFn: fileAccessApi.listExports,
  })
}

/** Delete export folders (links or copies; stored files are never touched). */
export function useRemoveExports() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (paths: string[]) => fileAccessApi.removeExports(paths),
    onSuccess: () => qc.invalidateQueries({ queryKey: EXPORTS }),
  })
}
