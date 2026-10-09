import {
  keepPreviousData,
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import {
  transfersApi,
  type Transfer,
  type TransferSpec,
} from '../api/transfers'
import { isBusy } from '../utils/transfers'

const KEY = ['store', 'transfers']

/** Everything that says how much is where: a move changes all of it. */
function refreshStorage(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: ['store', 'volumes'] })
  qc.invalidateQueries({ queryKey: ['store', 'collection'] })
  qc.invalidateQueries({ queryKey: ['file-listing'] })
}

/** Whether a move that was under way has stopped since the last look. */
export function someEnded(
  before: Transfer[] | undefined,
  now: Transfer[],
): boolean {
  if (!before) return false
  const busy = new Set(before.filter(isBusy).map((t) => t.id))
  return now.some((t) => busy.has(t.id) && !isBusy(t))
}

/** Recent transfers. Polls quickly while one is running and slowly otherwise.
 * When a move ends, the volumes' sizes and where each collection's files are
 * are asked again, so they don't wait for a page reload. */
export function useTransfers() {
  const qc = useQueryClient()
  return useQuery({
    queryKey: KEY,
    queryFn: async () => {
      const before = qc.getQueryData<Transfer[]>(KEY)
      const now = await transfersApi.list()
      if (someEnded(before, now)) refreshStorage(qc)
      return now
    },
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
      refreshStorage(qc)
    },
  })
}

export const useStartTransfer = () => useAction(transfersApi.start)
export const usePauseTransfer = () => useAction(transfersApi.pause)
export const useResumeTransfer = () => useAction(transfersApi.resume)
export const useCancelTransfer = () => useAction(transfersApi.cancel)
