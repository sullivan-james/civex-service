import { useEffect } from 'react'
import { useSearchParams } from 'react-router'
import { useActiveJobCount, useDrainJobs } from '../hooks/useWorkflows'
import { Page, Button } from '../components/ui'
import { RefreshCw } from '../components/ui/icons'
import JobsTable from '../components/jobs/JobsTable'

export default function JobsPage() {
  // `?status=failed` (the analytics widgets' "View runs" links) becomes the
  // same filter the table's own editor builds, so there is one way to say it.
  const [searchParams, setSearchParams] = useSearchParams()
  const legacyStatus = searchParams.get('status')
  useEffect(() => {
    if (!legacyStatus) return
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete('status')
        if (!next.has('filter'))
          next.set(
            'filter',
            JSON.stringify({ field: 'status', op: 'eq', value: legacyStatus }),
          )
        return next
      },
      { replace: true },
    )
  }, [legacyStatus, setSearchParams])

  const { data: activeJobs } = useActiveJobCount()
  const drain = useDrainJobs()

  const hasActive = (activeJobs?.running ?? 0) + (activeJobs?.pending ?? 0) > 0
  const hasPending = (activeJobs?.pending ?? 0) > 0

  return (
    <Page
      title="Runs"
      meta={
        hasActive ? (
          <span className="flex items-center gap-1 text-accent">
            <RefreshCw size={12} className="animate-spin" /> live
          </span>
        ) : undefined
      }
      action={
        <Button
          size="sm"
          variant={hasPending ? 'primary' : 'default'}
          onClick={() => drain.mutate()}
          disabled={drain.isPending}
        >
          {drain.isPending && <RefreshCw size={12} className="animate-spin" />}
          {drain.isPending ? 'Running…' : 'Run automation'}
        </Button>
      }
    >
      <JobsTable />
    </Page>
  )
}
