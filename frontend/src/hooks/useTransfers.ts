import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import {
  transfersApi,
  type Transfer,
  type TransferSpec,
} from '../api/transfers'

const KEY = ['store', 'transfers']

const isBusy = (t: Transfer) => t.status === 'running' || t.auto_resume

/** Recent transfers. Polls quickly while one is running and slowly otherwise. */
export function useTransfers() {
  return useQuery({
    queryKey: KEY,
    queryFn: transfersApi.list,
    refetchInterval: (q) => (q.state.data?.some(isBusy) ? 1000 : 15_000),
  })
}

/** What a transfer would do; re-asked as the form changes, never changes anything. */
export function useTransferPreview(spec: TransferSpec | null) {
  return useQuery({
    queryKey: [...KEY, 'preview', spec],
    queryFn: () => transfersApi.preview(spec as TransferSpec),
    enabled: spec !== null,
    placeholderData: keepPreviousData,
    retry: false,
  })
}

function useAction<A>(fn: (arg: A) => Promise<Transfer>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY })
      qc.invalidateQueries({ queryKey: ['store', 'volumes'] })
      qc.invalidateQueries({ queryKey: ['store', 'collection'] })
    },
  })
}

export const useStartTransfer = () => useAction(transfersApi.start)
export const usePauseTransfer = () => useAction(transfersApi.pause)
export const useResumeTransfer = () => useAction(transfersApi.resume)
export const useCancelTransfer = () => useAction(transfersApi.cancel)
