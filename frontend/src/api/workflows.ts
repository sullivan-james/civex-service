import { api } from './client'

export interface Workflow {
  name: string
  description: string | null
  steps: number
  filename: string
  stem: string
}

export interface WorkflowDetail extends Workflow {
  content: string
}

export interface WorkflowJob {
  id: string
  workflow_name: string
  record_id: string
  schema_name: string
  trigger: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  error: string | null
  log: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export const workflowsApi = {
  list:   ()                                          => api.get<Workflow[]>('/workflows'),
  get:    (stem: string)                              => api.get<WorkflowDetail>(`/workflows/${encodeURIComponent(stem)}`),
  save:   (stem: string, content: string)             => api.put<WorkflowDetail>(`/workflows/${encodeURIComponent(stem)}`, { content }),
  delete: (stem: string)                              => api.delete<void>(`/workflows/${encodeURIComponent(stem)}`),
  run:    (name: string, record_id: string)           => api.post<WorkflowJob>(`/workflows/${encodeURIComponent(name)}/run`, { record_id }),
}

export const jobsApi = {
  list: (status?: string, recordId?: string) => {
    const p = new URLSearchParams()
    if (status)   p.set('status', status)
    if (recordId) p.set('record_id', recordId)
    const qs = p.toString()
    return api.get<WorkflowJob[]>(`/jobs${qs ? `?${qs}` : ''}`)
  },
  get:   (id: string) => api.get<WorkflowJob>(`/jobs/${id}`),
  rerun: (id: string) => api.post<WorkflowJob>(`/jobs/${id}/rerun`, {}),
  drain: ()           => api.post<{ status: string }>('/jobs/drain', {}),
}
