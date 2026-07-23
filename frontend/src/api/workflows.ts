import { api } from './client'

export interface WorkflowInput {
  type: string
  label: string | null
  description: string | null
}

export interface Workflow {
  name: string
  description: string | null
  steps: number
  filename: string
  stem: string
  record_schema: string | null
  inputs: Record<string, WorkflowInput> | null
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
  list: () => api.get<Workflow[]>('/workflows'),
  get: (stem: string) =>
    api.get<WorkflowDetail>(`/workflows/${encodeURIComponent(stem)}`),
  save: (stem: string, content: string) =>
    api.put<WorkflowDetail>(`/workflows/${encodeURIComponent(stem)}`, {
      content,
    }),
  delete: (stem: string, force = false) =>
    api.delete<void>(
      `/workflows/${encodeURIComponent(stem)}${force ? '?force=true' : ''}`,
    ),
  run: (name: string, record_id: string) =>
    api.post<WorkflowJob>(`/workflows/${encodeURIComponent(name)}/run`, {
      record_id,
    }),

  runWithFiles: async (
    name: string,
    recordId: string,
    fileInputs: Record<string, File[]>,
  ): Promise<WorkflowJob> => {
    const form = new FormData()
    form.append('record_id', recordId)
    for (const [inputName, files] of Object.entries(fileInputs)) {
      for (const file of files) {
        form.append(inputName, file)
      }
    }
    const res = await fetch(`/api/workflows/${encodeURIComponent(name)}/run`, {
      method: 'POST',
      body: form,
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? `HTTP ${res.status}`)
    }
    return res.json()
  },
}

export const jobsApi = {
  list: (
    status?: string,
    recordId?: string,
    offset?: number,
    limit?: number,
  ) => {
    const p = new URLSearchParams()
    if (status) p.set('status', status)
    if (recordId) p.set('record_id', recordId)
    if (offset !== undefined) p.set('offset', String(offset))
    if (limit !== undefined) p.set('limit', String(limit))
    const qs = p.toString()
    return api.get<WorkflowJob[]>(`/jobs${qs ? `?${qs}` : ''}`)
  },
  count: (status?: string, recordId?: string) => {
    const p = new URLSearchParams()
    if (status) p.set('status', status)
    if (recordId) p.set('record_id', recordId)
    const qs = p.toString()
    return api.get<{ total: number }>(`/jobs/count${qs ? `?${qs}` : ''}`)
  },
  get: (id: string) => api.get<WorkflowJob>(`/jobs/${id}`),
  rerun: (id: string) => api.post<WorkflowJob>(`/jobs/${id}/rerun`, {}),
  drain: () => api.post<{ status: string }>('/jobs/drain', {}),
}
