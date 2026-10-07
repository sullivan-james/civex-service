import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import {
  restoreApi,
  type RestorePlan,
  type RestoreTarget,
} from '../api/restore'
import { auditApi, type AuditEventQuery } from '../api/audit'
import { recordsApi } from '../api/records'
import { useToast } from '../components/ui/ToastProvider'
import { errorMessage } from '../lib/errors'
import { invalidateRecordNames } from './useRecordName'

/** What restoring `target` would do, asked fresh each time: it describes the
 * trash as it is now. */
export function useRestorePlan(target: RestoreTarget, enabled = true) {
  return useQuery({
    queryKey: ['restore-plan', target.kind, target.ref],
    queryFn: () => restoreApi.plan(target),
    enabled,
    gcTime: 0,
  })
}

/** Where to look at the thing that came back. */
function whereTo(plan: RestorePlan): string {
  if (plan.kind === 'record') return `/records/${plan.id}`
  if (plan.kind === 'collection') return `/collections/${plan.id}`
  if (plan.kind === 'field') return `/schemas/${plan.schema_name}`
  return `/schemas/${plan.id}`
}

/** What the restore did, in a sentence, for the toast that follows it. */
export function restoreReceipt(plan: RestoreVars): string {
  const more = (n: number) =>
    `${n.toLocaleString()} record${n === 1 ? '' : 's'}`
  if (plan.kind === 'record') {
    const place = plan.collection ? ` to ${plan.collection}` : ''
    const parents = plan.withParents ? (plan.parents_needed ?? 0) : 0
    const above = parents > 0 ? ` and the ${more(parents)} above it` : ''
    if (plan.onlyThis) return `Restored just "${plan.name}"${place}${above}`
    const extra = plan.records - 1
    return `Restored "${plan.name}"${place}${above}${extra > 0 ? `, with ${more(extra)} deleted alongside it` : ''}`
  }
  if (plan.kind === 'field')
    return `Restored field "${plan.name}" on "${plan.schema_name}"`
  const what = plan.kind === 'collection' ? 'collection' : 'schema'
  return `Restored ${what} "${plan.name}"${plan.records > 0 ? ` and ${more(plan.records)}` : ''}`
}

/** A plan to carry out, with the choices a delete leaves open: `onlyThis`
 * leaves what was deleted alongside the record deleted, and `withParents`
 * brings back the deleted records above it, each by itself, leaving their other
 * children deleted. */
export type RestoreVars = RestorePlan & {
  onlyThis?: boolean
  withParents?: boolean
}

/** Restore what `plan` describes. Says what came back and where, with a link
 * to it, so the result can be seen. */
export function useRestore(onDone?: () => void) {
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: (plan: RestoreVars) =>
      restoreApi.restore({
        kind: plan.kind,
        ref:
          plan.kind === 'record' || plan.kind === 'field' ? plan.id : plan.name,
        schema: plan.schema_name ?? undefined,
        onlyThis: plan.onlyThis,
        withParents: plan.withParents,
      }),
    onSuccess: (_data, plan) => {
      toast.success(restoreReceipt(plan), {
        action: { label: 'View', onClick: () => navigate(whereTo(plan)) },
        duration: 10_000,
      })
      onDone?.()
    },
    onError: (error) => toast.error(errorMessage(error)),
    onSettled: () => refreshAfterRestore(qc),
  })
}

/** Every cache a restore can change. The one list, for anything that brings
 * things back. */
export function refreshAfterRestore(qc: QueryClient) {
  for (const key of [
    'records',
    'record',
    'record-counts',
    'record-audit',
    'records-deleted',
    'records-orphans',
    'collections',
    'collections-deleted',
    'schemas',
    'schemas-deleted',
    'trash',
    'audit',
    'restore-plan',
    'audit-revert-plan',
    'remote',
  ])
    qc.invalidateQueries({ queryKey: [key] })
  invalidateRecordNames(qc)
}

/** Live records that sit under a deleted record (out of sight). */
export function useOrphans() {
  return useQuery({
    queryKey: ['records-orphans'],
    queryFn: () => recordsApi.orphans(),
  })
}

/** Bring back what a live record sits under that is deleted (each by itself,
 * so their other children stay deleted). */
export function useRestoreAbove() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (id: string) => recordsApi.restoreAbove(id),
    onSuccess: (restored) =>
      toast.success(
        `Restored ${restored
          .map((r) => r.natural_name ?? r.schema_name)
          .join(' › ')}`,
      ),
    onError: (error) => toast.error(errorMessage(error)),
    onSettled: () => refreshAfterRestore(qc),
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
            ? `. ${n(result.blocked, 'thing')} stay deleted: something they belong to is still deleted, or a field's name has been taken.`
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

/** Restore exactly the records picked from a bulk delete, leaving the rest of
 * it deleted. Says how many came back, and how many could not. */
export function useRestoreSelected(onDone?: () => void) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (ids: string[]) => recordsApi.restoreSelected(ids),
    onSuccess: (result) => {
      const n = (c: number, w: string) =>
        `${c.toLocaleString()} ${w}${c === 1 ? '' : 's'}`
      const extra = result.came_back - result.restored
      toast.success(
        `Restored ${n(result.restored, 'record')}` +
          (extra > 0 ? `, and ${n(extra, 'record')} above to hold them` : '') +
          (result.left
            ? `. ${n(result.left, 'record')} stay deleted: something they belong to is deleted.`
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
