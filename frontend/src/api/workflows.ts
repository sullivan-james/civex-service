import { api } from './client'
import type { FilterTreeWire } from '../utils/filterTree'

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
  /** What starts it by itself, one line each; empty if only run by hand. */
  runs_on: string[]
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
  /** Only on runs made before names stopped being stored (names are worked out
   * when looked at: `POST /records/labels`). */
  natural_name?: string | null
  action: 'created' | 'updated'
}

export interface ErrorDetails {
  kind: string
  message: string
  retryable: boolean
  step: string | null
}

/** One field that changed to start a run. */
export interface TriggerChange {
  field: string
  /** Short forms: a file shows its name, a list its length; null for nothing. */
  before: string | null
  after: string | null
  /** Whether the workflow's trigger was watching this field. */
  watched: boolean
}

/** What started a run, beyond the event name. */
export interface TriggerDetail {
  changes: TriggerChange[]
  /** The run whose own save started this one, when there is one. */
  caused_by: { job_id: string; workflow: string | null } | null
}

export interface WorkflowJob {
  id: string
  workflow_name: string
  record_id: string
  schema_name: string
  trigger: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  error: string | null
  error_details: ErrorDetails | null
  log: string | null
  step_executions: StepExecution[] | null
  affected_records: AffectedRecord[] | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  /** 0 for a run started by a person or an edit; 1 for one started by another
   * run's save; and so on. */
  depth: number
  /** Null for a run started by hand, or one from before this was recorded. */
  trigger_detail: TriggerDetail | null
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
  /** One run of a workflow per record, in one request. */
  runMany: (name: string, record_ids: string[]) =>
    api.post<RerunResult>(`/workflows/${encodeURIComponent(name)}/run-many`, {
      record_ids,
    }),
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
  /** Only runs of the workflow with exactly this name. */
  workflow?: string
  trigger?: string
  search?: string
  /** `column:asc|desc` */
  sort?: string
  /** The same filter tree the records explorer uses, over run fields. */
  filter?: FilterTreeWire | null
}

function setRunQuery(p: URLSearchParams, q?: RunQuery) {
  if (q?.workflow) p.set('workflow', q.workflow)
  if (q?.trigger) p.set('trigger', q.trigger)
  if (q?.search) p.set('search', q.search)
  if (q?.sort) p.set('sort', q.sort)
  if (q?.filter) p.set('filter', JSON.stringify(q.filter))
}

/** What repeating several runs came to: the new runs, and any that couldn't be
 * repeated, with why. */
export interface RerunResult {
  started: WorkflowJob[]
  skipped: { id: string; reason: string }[]
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
  cancel: (id: string) => api.post<WorkflowJob>(`/jobs/${id}/cancel`, {}),
  /** Repeat several runs in one request. */
  rerunMany: (which: { ids: string[] } | { filter: FilterTreeWire }) =>
    api.post<RerunResult>('/jobs/rerun', which),
  /** Delete runs, whatever their state: a waiting one never starts. */
  deleteMany: (which: { ids: string[] } | { filter: FilterTreeWire }) =>
    api.post<{ deleted: number }>('/jobs/delete', which),
  filterFields: () => api.get<RunFilterField[]>('/jobs/filter-fields'),
  failureGroups: (filter?: FilterTreeWire | null) =>
    api.get<FailureGroup[]>(
      `/jobs/failure-groups${filter ? `?filter=${encodeURIComponent(JSON.stringify(filter))}` : ''}`,
    ),
  drain: () => api.post<{ status: string }>('/jobs/drain', {}),
}

export interface AutomationStatus {
  /** While true nothing new starts: triggers fire nothing and manual runs are
   * refused. */
  paused: boolean
  pending: number
  running: number
  /** How many runs a stop just cancelled. */
  cancelled: number
  /** The current stretch of work, counted by the server; null when idle. */
  batch: AutomationBatch | null
}

export interface AutomationBatch {
  total: number
  active: number
  completed: number
  failed: number
  cancelled: number
  started_at: string
}

/** A field a run filter may test (`GET /jobs/filter-fields`). */
export interface RunFilterField {
  name: string
  label: string
  type: string
  description: string
  choices: string[] | null
  operators: string[]
}

/** Failed runs that failed the same way. */
export interface FailureGroup {
  workflow: string
  kind: string | null
  step: string | null
  message: string | null
  count: number
  last_at: string
}

export const automationApi = {
  status: () => api.get<AutomationStatus>('/automation'),
  stop: () => api.post<AutomationStatus>('/automation/stop', {}),
  resume: () => api.post<AutomationStatus>('/automation/resume', {}),
}
