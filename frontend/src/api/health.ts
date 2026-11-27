import { api } from './client'

export interface HealthCheck {
  name: string
  status: 'ok' | 'warn' | 'fail'
  detail: string
  fix: string
}

export interface HealthProblem {
  kind: string
  severity: 'warn' | 'fail'
  message: string
  fix: string
  items: string[]
}

/** What `civex doctor` checks (`services/health_service.py`). */
export interface Health {
  ok: boolean
  problems: HealthProblem[]
  /** The install checks; null where this server has no install to check. */
  checks: HealthCheck[] | null
  data_checked: boolean
  can_repair: boolean
  repair_offered: boolean
}

export interface RepairResult {
  backup: string
  added: string[]
  health: Health
}

export const healthApi = {
  check: () => api.get<Health>('/health'),
  repair: () => api.post<RepairResult>('/health/repair', {}),
}
