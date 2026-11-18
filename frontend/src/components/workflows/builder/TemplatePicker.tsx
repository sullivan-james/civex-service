import { Card } from '../../ui'
import {
  WORKFLOW_TEMPLATES,
  type WorkflowTemplate,
} from '../../../utils/workflowTemplates'

/** "New workflow": what to start from. Every choice opens the same builder. */
export function TemplatePicker({
  onPick,
}: {
  onPick: (template: WorkflowTemplate) => void
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {WORKFLOW_TEMPLATES.map((t) => (
        <Card
          key={t.id}
          variant="interactive"
          title={t.title}
          onClick={() => onPick(t)}
        >
          <p className="text-sm text-fg-muted">{t.description}</p>
        </Card>
      ))}
    </div>
  )
}
