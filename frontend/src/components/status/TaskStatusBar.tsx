import { Link } from 'react-router'
import { useBackgroundTasks } from '../../hooks/useBackgroundTasks'
import type { BackgroundTask, TaskAction } from '../../utils/backgroundTasks'
import { Button, ProgressBar } from '../ui'

function Action({ action }: { action: TaskAction }) {
  if (action.to)
    return (
      <Link to={action.to} className="text-accent hover:underline">
        {action.label}
      </Link>
    )
  return (
    <Button
      size="sm"
      variant={action.variant}
      disabled={action.disabled}
      onClick={action.onClick}
    >
      {action.label}
    </Button>
  )
}

function TaskRow({ task }: { task: BackgroundTask }) {
  const Icon = task.icon
  const attention = task.tone === 'attention'
  return (
    <div
      className={`px-4 py-2 text-sm ${
        attention
          ? 'bg-attention-subtle text-attention'
          : 'bg-canvas-subtle text-fg'
      }`}
    >
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-4 gap-y-1">
        <Icon
          size={16}
          className={`${task.spinning ? 'animate-spin' : ''} ${attention ? 'text-attention' : 'text-fg-muted'}`}
          aria-hidden="true"
        />
        <p className={task.progress ? 'font-medium' : ''}>{task.title}</p>
        {task.progress && (
          <ProgressBar
            fraction={task.progress.fraction}
            label={task.progress.label}
          />
        )}
        {task.detail && <p className="text-fg-muted">{task.detail}</p>}
        {task.note && <span className="text-fg-muted">{task.note}</span>}
        {task.actions && task.actions.length > 0 && (
          <span className="ml-auto flex items-center gap-3">
            {task.actions.map((a) => (
              <Action key={a.label} action={a} />
            ))}
          </span>
        )}
      </div>
    </div>
  )
}

/** The bottom bar, for whatever tasks it is given: one row each, stacked.
 * Renders nothing when there are none. */
export function StatusBar({ tasks }: { tasks: BackgroundTask[] }) {
  if (tasks.length === 0) return null
  return (
    <>
      <div
        role="status"
        aria-live="polite"
        className="shrink-0 divide-y divide-border border-t border-border"
      >
        {tasks.map((t) => (
          <TaskRow key={t.id} task={t} />
        ))}
      </div>
      {tasks.map((t) =>
        t.overlay ? <span key={`${t.id}:overlay`}>{t.overlay}</span> : null,
      )}
    </>
  )
}

/** The app's status bar: every background task there is, wherever you are. */
export function TaskStatusBar() {
  return <StatusBar tasks={useBackgroundTasks()} />
}
