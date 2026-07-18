import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { jobsApi, workflowsApi, type WorkflowJob } from '../api/workflows'

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
  return useMutation({
    mutationFn: ({ stem, content }: { stem: string; content: string }) =>
      workflowsApi.save(stem, content),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['workflows'] }),
  })
}

export function useDeleteWorkflow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (stem: string) => workflowsApi.delete(stem),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['workflows'] }),
  })
}

export function useRunWorkflow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, recordId }: { name: string; recordId: string }) =>
      workflowsApi.run(name, recordId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
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
) {
  const offset = page * pageSize
  const jobs = useQuery({
    queryKey: ['jobs', 'paged', page, pageSize, status, recordId],
    queryFn: () => jobsApi.list(status, recordId, offset, pageSize),
    refetchInterval: (query) => {
      const data = query.state.data as WorkflowJob[] | undefined
      return data?.some((j) => j.status === 'pending' || j.status === 'running')
        ? 2000
        : 5000
    },
  })
  const total = useQuery({
    queryKey: ['jobs', 'count', status, recordId],
    queryFn: () => jobsApi.count(status, recordId),
    refetchInterval: 5000,
  })
  return {
    jobs,
    total: total.data?.total ?? 0,
    isLoading: jobs.isLoading || total.isLoading,
    error: jobs.error,
  }
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
    refetchInterval: 3000,
  })
}

export function useRerunJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => jobsApi.rerun(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function useDrainJobs() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: jobsApi.drain,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
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
