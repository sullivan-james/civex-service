import { type WorkflowJob } from '../../api/workflows'
import { Badge } from '../ui'
import { Check, XCircle, RefreshCw, Clock } from '../ui/icons'

export default function JobStatusBadge({
  status,
}: {
  status: WorkflowJob['status']
}) {
  switch (status) {
    case 'completed':
      return (
        <Badge variant="success" className="gap-1">
          <Check size={12} /> completed
        </Badge>
      )
    case 'failed':
      return (
        <Badge variant="danger" className="gap-1">
          <XCircle size={12} /> failed
        </Badge>
      )
    case 'running':
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-accent">
          <RefreshCw size={12} className="animate-spin" /> running
        </span>
      )
    default:
      return (
        <Badge variant="default" className="gap-1">
          <Clock size={12} /> pending
        </Badge>
      )
  }
}
