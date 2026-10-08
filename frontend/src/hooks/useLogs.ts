import { useQuery } from '@tanstack/react-query'
import { logsApi, type LogQuery } from '../api/logs'

export function useLogSources() {
  return useQuery({ queryKey: ['logs'], queryFn: logsApi.list })
}

/** A log's latest lines; `follow` reads them again every two seconds. */
export function useLog(id: string | null, query: LogQuery, follow: boolean) {
  return useQuery({
    queryKey: ['logs', id, query],
    queryFn: () => logsApi.read(id!, query),
    enabled: !!id,
    refetchInterval: follow ? 2000 : false,
    placeholderData: (previous) => previous,
  })
}
