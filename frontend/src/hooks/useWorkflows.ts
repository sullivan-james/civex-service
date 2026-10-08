import {
  keepPreviousData,
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import {
  automationApi,
  jobsApi,
  workflowsApi,
  type AutomationStatus,
  type RunQuery,
  type WorkflowJob,
} from '../api/workflows'
import { useToast } from '../components/ui/ToastProvider'
import type { FilterTreeWire } from '../utils/filterTree'

/** After anything that queues, finishes or stops runs: the lists, and the status
 * bar's tracker at once, instead of whenever it next polls (idle, that is every
 * 15 seconds, long enough for a bulk start to go unseen). */
function refreshRuns(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: ['jobs'] })
  qc.invalidateQueries({ queryKey: ['automation'] })
}

export function useWorkflows() {
  return useQuery({ queryKey: ['workflows'], queryFn: workflowsApi.list })
}

export function useWorkflow(stem: string) {
  return useQuery({
    queryKey: ['workflows', stem],
    queryFn: () => workflowsApi.get(stem),
    enabled: !!stem,
  })
}

export function useSaveWorkflow() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: ({ stem, content }: { stem: string; content: string }) =>
      workflowsApi.save(stem, content),
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: ['workflows'] })
      toast.success(`Workflow "${saved.name}" saved`)
    },
  })
}

export function useDeleteWorkflow() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: ({ stem, force }: { stem: string; force?: boolean }) =>
      workflowsApi.delete(stem, force),
    onSuccess: (_data, { stem }) => {
      qc.invalidateQueries({ queryKey: ['workflows'] })
      toast.success(`Workflow "${stem}" deleted`)
    },
  })
}

export function useRunWorkflow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, recordId }: { name: string; recordId: string }) =>
      workflowsApi.run(name, recordId),
    onSuccess: () => refreshRuns(qc),
  })
}

/** Run one workflow on several records at once. */
export function useRunWorkflowOnMany() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, recordIds }: { name: string; recordIds: string[] }) =>
      workflowsApi.runMany(name, recordIds),
    onSuccess: () => refreshRuns(qc),
  })
}

export function useRunWorkflowWithFiles() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      name,
      recordId,
      fileInputs,
    }: {
      name: string
      recordId: string
      fileInputs: Record<string, File[]>
    }) => workflowsApi.runWithFiles(name, recordId, fileInputs),
    onSuccess: () => refreshRuns(qc),
  })
}

export function useJobs(status?: string, recordId?: string) {
  return useQuery({
    queryKey: ['jobs', status, recordId],
    queryFn: () => jobsApi.list(status, recordId),
    refetchInterval: (query) => {
      const jobs = query.state.data as WorkflowJob[] | undefined
      // Fast poll while jobs are active; slow baseline so newly-triggered
      // jobs (e.g. from record create/update hooks) appear without a manual refresh.
      return jobs?.some((j) => j.status === 'pending' || j.status === 'running')
        ? 2000
        : 5000
    },
  })
}

export function useJobsPaged(
  page: number,
  pageSize: number,
  status?: string,
  recordId?: string,
  query?: RunQuery,
) {
  const offset = page * pageSize
  const jobs = useQuery({
    queryKey: ['jobs', 'paged', page, pageSize, status, recordId, query],
    queryFn: () =>
      jobsApi.list(status, recordId, offset, pageSize, undefined, query),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => {
      const data = query.state.data as WorkflowJob[] | undefined
      return data?.some((j) => j.status === 'pending' || j.status === 'running')
        ? 2000
        : 5000
    },
  })
  const total = useQuery({
    queryKey: ['jobs', 'count', status, recordId, query],
    queryFn: () => jobsApi.count(status, recordId, undefined, query),
    placeholderData: keepPreviousData,
    refetchInterval: 5000,
  })
  return {
    jobs,
    total: total.data?.total ?? 0,
    isLoading: jobs.isLoading || total.isLoading,
    isFetching: jobs.isFetching || total.isFetching,
    error: jobs.error,
  }
}

export function useJobsAffectingRecord(recordId: string) {
  return useQuery({
    queryKey: ['jobs', 'affecting', recordId],
    queryFn: () => jobsApi.list(undefined, undefined, 0, 10, recordId),
    enabled: !!recordId,
  })
}

export function useActiveJobCount() {
  return useQuery({
    queryKey: ['jobs', 'count', 'active'],
    queryFn: async () => {
      const [r, p] = await Promise.all([
        jobsApi.count('running'),
        jobsApi.count('pending'),
      ])
      return { running: r.total, pending: p.total }
    },
    // This runs in the app shell on every page, so back off when idle;
    // the jobs mutations invalidate ['jobs'] and refresh it immediately.
    refetchInterval: (query) => {
      const counts = query.state.data
      return counts && counts.running + counts.pending > 0 ? 3000 : 15_000
    },
  })
}

export function useRerunJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => jobsApi.rerun(id),
    onSuccess: () => refreshRuns(qc),
  })
}

export function useDrainJobs() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: jobsApi.drain,
    onSuccess: () => refreshRuns(qc),
  })
}

export function useJob(id: string) {
  return useQuery({
    queryKey: ['job', id],
    queryFn: () => jobsApi.get(id),
    enabled: !!id,
    refetchInterval: (query) => {
      const job = query.state.data as WorkflowJob | undefined
      return job && (job.status === 'pending' || job.status === 'running')
        ? 2000
        : false
    },
  })
}

/** Repeat several runs at once (one request). */
export function useRerunJobs() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (which: { ids: string[] } | { filter: FilterTreeWire }) =>
      jobsApi.rerunMany(which),
    onSuccess: () => refreshRuns(qc),
  })
}

/** Delete runs (one request): a waiting one never starts, a running one stops
 * before its next step. */
export function useDeleteJobs() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (which: { ids: string[] } | { filter: FilterTreeWire }) =>
      jobsApi.deleteMany(which),
    onSuccess: () => {
      refreshRuns(qc)
      qc.invalidateQueries({ queryKey: ['job'] })
      qc.invalidateQueries({ queryKey: ['automation'] })
    },
  })
}

export function useCancelJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => jobsApi.cancel(id),
    onSuccess: () => {
      refreshRuns(qc)
      qc.invalidateQueries({ queryKey: ['job'] })
      qc.invalidateQueries({ queryKey: ['automation'] })
    },
  })
}

/** Whether automation is paused, and how many runs wait or run. Runs in the
 * app shell, so it backs off when nothing is going on. */
/** The fields a run filter may test, from the server. */
export function useRunFilterFields() {
  return useQuery({
    queryKey: ['jobs', 'filter-fields'],
    queryFn: jobsApi.filterFields,
    staleTime: Infinity,
  })
}

/** Failed runs grouped by what went wrong, for the runs a filter covers. */
export function useFailureGroups(
  filter: FilterTreeWire | null,
  enabled = true,
) {
  return useQuery({
    queryKey: ['jobs', 'failure-groups', filter],
    queryFn: () => jobsApi.failureGroups(filter),
    enabled,
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  })
}

export function useAutomation() {
  return useQuery({
    queryKey: ['automation'],
    queryFn: automationApi.status,
    refetchInterval: (query) => {
      const s = query.state.data
      // While runs are going: often, so the tracker follows them closely.
      return s && (s.paused || s.pending + s.running > 0) ? 1500 : 15_000
    },
  })
}

function useAutomationAction(fn: () => Promise<AutomationStatus>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['automation'] })
      refreshRuns(qc)
      qc.invalidateQueries({ queryKey: ['job'] })
    },
  })
}

export const useStopAutomation = () => useAutomationAction(automationApi.stop)
export const useResumeAutomation = () =>
  useAutomationAction(automationApi.resume)
