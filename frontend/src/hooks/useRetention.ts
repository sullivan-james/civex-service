import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { retentionApi, type RetentionRequest } from '../api/retention'
import { useToast } from '../components/ui/ToastProvider'
import { errorMessage } from '../lib/errors'

/** What a clean-up would remove, counted without removing it. */
export function useRetentionPreview(request: RetentionRequest) {
  return useQuery({
    queryKey: ['retention', 'preview', request],
    queryFn: () => retentionApi.run(request, true),
    gcTime: 0,
  })
}

/** Run a clean-up for real, and refresh everything it can have changed. */
export function useRunRetention(onDone?: () => void) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (request: RetentionRequest) => retentionApi.run(request, false),
    onSuccess: () => {
      toast.success('Clean-up finished')
      onDone?.()
    },
    onError: (error) => toast.error(errorMessage(error)),
    onSettled: () => {
      for (const key of [
        'audit',
        'records',
        'collections',
        'schemas',
        'jobs',
        'retention',
        'record-counts',
      ])
        qc.invalidateQueries({ queryKey: [key] })
    },
  })
}

/** How many history entries still hold the values of records that were
 * permanently deleted. Zero once permanent deletes do their own clean-up. */
export function usePurgedHistory() {
  return useQuery({
    queryKey: ['retention', 'purged-history'],
    queryFn: () => retentionApi.purgedHistory(true),
  })
}

/** Delete that history, leaving each record a tombstone. */
export function useForgetPurgedHistory(onDone?: () => void) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: () => retentionApi.purgedHistory(false),
    onSuccess: (result) => {
      toast.success(
        `Deleted ${result.entries.toLocaleString()} history entries`,
      )
      onDone?.()
    },
    onError: (error) => toast.error(errorMessage(error)),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['retention'] })
      qc.invalidateQueries({ queryKey: ['audit'] })
    },
  })
}
