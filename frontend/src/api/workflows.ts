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

export interface WorkflowTrigger {
  schema_name: string
  fields: string[] | null
}

export interface WorkflowStep {
  id: string
  plugin: string
  config: Record<string, unknown>
  inputs: Record<string, string>
  condition: string | null
}

export interface WorkflowDetail extends Workflow {
  content: string
  step_list: WorkflowStep[]
  triggers: Record<string, WorkflowTrigger> | null
}

export interface StepExecution {
  step_id: string
  plugin: string
  status: 'success' | 'failed' | 'skipped'
  inputs: Record<string, unknown>
  outputs: Record<string, unknown> | null
  duration_seconds: number
  error: string | null
  depends_on: string[]
}

export interface AffectedRecord {
  record_id: string
  schema_name: string
  natural_name: string | null
  action: 'created' | 'updated'
}

export interface ErrorDetails {
  kind: string
  message: string
  retryable: boolean
  step: string | null
}

export interface WorkflowJob {
  id: string
  workflow_name: string
  record_id: string
  schema_name: string
  trigger: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  error: string | null
  error_details: ErrorDetails | null
  log: string | null
  step_executions: StepExecution[] | null
  affected_records: AffectedRecord[] | null
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

/** The narrowing a run list can ask for beyond status and record. */
export interface RunQuery {
  trigger?: string
  search?: string
  /** `column:asc|desc` */
  sort?: string
}

function setRunQuery(p: URLSearchParams, q?: RunQuery) {
  if (q?.trigger) p.set('trigger', q.trigger)
  if (q?.search) p.set('search', q.search)
  if (q?.sort) p.set('sort', q.sort)
}

export const jobsApi = {
  list: (
    status?: string,
    recordId?: string,
    offset?: number,
    limit?: number,
    affectedRecordId?: string,
    query?: RunQuery,
  ) => {
    const p = new URLSearchParams()
    if (status) p.set('status', status)
    if (recordId) p.set('record_id', recordId)
    if (affectedRecordId) p.set('affected_record_id', affectedRecordId)
    setRunQuery(p, query)
    if (offset !== undefined) p.set('offset', String(offset))
    if (limit !== undefined) p.set('limit', String(limit))
    const qs = p.toString()
    return api.get<WorkflowJob[]>(`/jobs${qs ? `?${qs}` : ''}`)
  },
  count: (
    status?: string,
    recordId?: string,
    affectedRecordId?: string,
    query?: RunQuery,
  ) => {
    const p = new URLSearchParams()
    if (status) p.set('status', status)
    if (recordId) p.set('record_id', recordId)
    if (affectedRecordId) p.set('affected_record_id', affectedRecordId)
    setRunQuery(p, query)
    const qs = p.toString()
    return api.get<{ total: number }>(`/jobs/count${qs ? `?${qs}` : ''}`)
  },
  get: (id: string) => api.get<WorkflowJob>(`/jobs/${id}`),
  rerun: (id: string) => api.post<WorkflowJob>(`/jobs/${id}/rerun`, {}),
  drain: () => api.post<{ status: string }>('/jobs/drain', {}),
}
