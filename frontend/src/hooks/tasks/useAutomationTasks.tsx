import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, RefreshCw } from '../../components/ui/icons'
import { StopAutomationDialog } from '../../components/workflows/StopAutomationDialog'
import type { BackgroundTask } from '../../utils/backgroundTasks'
import { jobsApi, type AutomationBatch } from '../../api/workflows'
import {
  allOf,
  failedRuns,
  failedRunsHref,
  queuedSince,
} from '../../utils/runFilter'
import { useBusyFor } from '../useBusyFor'
import { useAutomation, useResumeAutomation } from '../useWorkflows'

/** How long workflows must have been busy before they show in the bar: an
 * ordinary edit starts a run that is over in a moment, and must not flash it. */
export const SHOW_AFTER_MS = 2000

/** How a batch that has ended came out, counted by the server: every run queued
 * since it began, and how many of those failed. */
function useBatchOutcome(since: string | null) {
  return useQuery({
    queryKey: ['jobs', 'batch-outcome', since],
    enabled: since !== null,
    queryFn: async () => {
      const [all, failed] = await Promise.all([
        jobsApi.count(undefined, undefined, undefined, {
          filter: queuedSince(since!),
        }),
        jobsApi.count(undefined, undefined, undefined, {
          filter: allOf(failedRuns(), queuedSince(since!)),
        }),
      ])
      return { total: all.total, failed: failed.total }
    },
  })
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)

/** Workflow runs, as tasks: a pause that must not be forgotten (and answers
 * "why did nothing run?"); the runs going on, as a batch counted by the server
 * -- so a bulk start of 50 shows as 50 at once, with how many succeeded and
 * failed so far, and failures count as done so a batch of nothing but errors
 * still moves; a way to stop a runaway loop without finding the right page; and,
 * once a batch ends with failures, a notice that stays until dismissed, linking
 * to exactly those runs. Nothing otherwise. */
export function useAutomationTasks(): BackgroundTask[] {
  const { data } = useAutomation()
  const resume = useResumeAutomation()
  const [stopping, setStopping] = useState(false)
  const batch = data?.paused ? null : (data?.batch ?? null)
  const active = batch?.active ?? 0
  // One run on its own mustn't flash; a batch is worth showing at once.
  const busy = useBusyFor(active > 0 && !data?.paused, SHOW_AFTER_MS)

  // The last batch seen, and one that ended: noticed while rendering (not in an
  // effect), so it settles in one pass.
  const [last, setLast] = useState<AutomationBatch | null>(null)
  const [ended, setEnded] = useState<AutomationBatch | null>(null)
  if (data && batch !== last) {
    if (batch) {
      setLast(batch)
      if (ended) setEnded(null)
    } else if (last) {
      setLast(null)
      setEnded(last)
    }
  }
  const outcome = useBatchOutcome(ended?.started_at ?? null)

  if (!data) return []

  if (data.paused)
    return [
      {
        id: 'automation',
        tone: 'attention',
        icon: AlertTriangle,
        title:
          "Automation is paused. Nothing new will run: edits don't start workflows, and manual runs are refused.",
        actions: [
          { label: 'See runs', to: '/runs' },
          {
            label: resume.isPending ? 'Resuming…' : 'Resume automation',
            variant: 'primary',
            disabled: resume.isPending,
            onClick: () => resume.mutate(),
          },
        ],
      },
    ]

  if (batch && active > 0 && (batch.total > 1 || busy)) {
    const done = batch.total - active
    return [
      {
        id: 'automation',
        tone: batch.failed > 0 ? 'attention' : 'info',
        icon: RefreshCw,
        spinning: true,
        title: 'Workflows are running',
        // A bar only for a batch: one run alone has nothing to measure.
        progress:
          batch.total > 1
            ? {
                fraction: done / batch.total,
                label: 'Workflow runs finished',
              }
            : undefined,
        // Runs go one at a time, so "1 running" would add nothing: say how far
        // through the batch it is, how it has gone so far, and what waits.
        detail:
          [
            batch.total > 1 && `${done} of ${batch.total} done`,
            batch.completed > 0 && `${batch.completed} succeeded`,
            batch.failed > 0 && `${batch.failed} failed`,
            data.pending > 0 && `${data.pending} waiting`,
          ]
            .filter(Boolean)
            .join(' · ') || undefined,
        actions: [
          ...(batch.failed > 0
            ? [
                {
                  label: `See ${batch.failed} failed`,
                  to: failedRunsHref(batch.started_at),
                },
              ]
            : []),
          { label: 'See runs', to: '/runs' },
          {
            label: 'Stop automation…',
            variant: 'danger' as const,
            onClick: () => setStopping(true),
          },
        ],
        overlay: stopping ? (
          <StopAutomationDialog onClose={() => setStopping(false)} />
        ) : undefined,
      },
    ]
  }

  // The batch is over, with failures: stays until dismissed, or a new batch.
  if (ended && outcome.data && outcome.data.failed > 0)
    return [
      {
        id: 'automation-failed',
        tone: 'attention',
        icon: AlertTriangle,
        title: `${outcome.data.failed.toLocaleString()} of ${outcome.data.total.toLocaleString()} workflow ${plural(outcome.data.total, 'run', 'runs')} failed`,
        actions: [
          {
            label: `See the ${plural(outcome.data.failed, 'failure', 'failures')}`,
            to: failedRunsHref(ended.started_at),
            variant: 'primary',
          },
          { label: 'Dismiss', onClick: () => setEnded(null) },
        ],
      },
    ]

  return []
}
