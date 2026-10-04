import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import {
  restoreApi,
  type RestorePlan,
  type RestoreTarget,
} from '../api/restore'
import { auditApi, type AuditEventQuery } from '../api/audit'
import { useToast } from '../components/ui/ToastProvider'
import { errorMessage } from '../lib/errors'
import { invalidateRecordNames } from './useRecordName'

/** What restoring `target` would do, asked fresh each time: it describes the
 * trash as it is now. */
export function useRestorePlan(target: RestoreTarget) {
  return useQuery({
    queryKey: ['restore-plan', target.kind, target.ref],
    queryFn: () => restoreApi.plan(target),
    gcTime: 0,
  })
}

/** Where to look at the thing that came back. */
function whereTo(plan: RestorePlan): string {
  if (plan.kind === 'record') return `/records/${plan.id}`
  if (plan.kind === 'collection') return `/collections/${plan.id}`
  return `/schemas/${plan.id}`
}

/** What the restore did, in a sentence, for the toast that follows it. */
export function restoreReceipt(plan: RestorePlan): string {
  const more = (n: number) =>
    `${n.toLocaleString()} record${n === 1 ? '' : 's'}`
  if (plan.kind === 'record') {
    const place = plan.collection ? ` to ${plan.collection}` : ''
    const extra = plan.records - 1
    return `Restored "${plan.name}"${place}${extra > 0 ? `, with ${more(extra)} deleted alongside it` : ''}`
  }
  const what = plan.kind === 'collection' ? 'collection' : 'schema'
  return `Restored ${what} "${plan.name}"${plan.records > 0 ? ` and ${more(plan.records)}` : ''}`
}

/** Restore what `plan` describes. Says what came back and where, with a link
 * to it, so the result can be seen. */
export function useRestore(onDone?: () => void) {
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: (plan: RestorePlan) =>
      restoreApi.restore({
        kind: plan.kind,
        ref: plan.kind === 'record' ? plan.id : plan.name,
      }),
    onSuccess: (_data, plan) => {
      toast.success(restoreReceipt(plan), {
        action: { label: 'View', onClick: () => navigate(whereTo(plan)) },
        duration: 10_000,
      })
      onDone?.()
    },
    onError: (error) => toast.error(errorMessage(error)),
    onSettled: () => {
      for (const key of [
        'records',
        'record',
        'record-counts',
        'record-audit',
        'records-deleted',
        'collections',
        'collections-deleted',
        'schemas',
        'schemas-deleted',
        'trash',
        'audit',
        'restore-plan',
        'audit-revert-plan',
      ])
        qc.invalidateQueries({ queryKey: [key] })
      invalidateRecordNames(qc)
    },
  })
}

/** What restoring everything deleted that a filter matches would do. Only asked
 * for while "Deleted" is showing. */
export function useRestoreAllPlan(query: AuditEventQuery, enabled: boolean) {
  return useQuery({
    queryKey: ['audit', 'restore-all-plan', query],
    queryFn: () => auditApi.restoreAllPlan(query),
    enabled,
    gcTime: 0,
  })
}

/** Restore everything deleted that a filter matches, and say what came back. */
export function useRestoreAll(onDone?: () => void) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (query: AuditEventQuery) => auditApi.restoreAll(query),
    onSuccess: (result) => {
      const n = (c: number, w: string) =>
        `${c.toLocaleString()} ${w}${c === 1 ? '' : 's'}`
      toast.success(
        `Restored ${n(result.restored, 'thing')}, ${n(result.records, 'record')} in all` +
          (result.blocked
            ? `. ${n(result.blocked, 'record')} stay deleted: a parent is still deleted.`
            : ''),
      )
      onDone?.()
    },
    onError: (error) => toast.error(errorMessage(error)),
    onSettled: () => {
      for (const key of [
        'records',
        'record',
        'record-counts',
        'record-audit',
        'records-deleted',
        'collections',
        'collections-deleted',
        'schemas',
        'schemas-deleted',
        'audit',
      ])
        qc.invalidateQueries({ queryKey: [key] })
      invalidateRecordNames(qc)
    },
  })
}
