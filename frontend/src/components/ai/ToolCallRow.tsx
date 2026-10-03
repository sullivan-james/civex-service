import { Disclosure } from '../ui'
import { Link } from 'react-router'
import type { ToolCallEntry } from '../../types/ai'
import CodeBlock from './CodeBlock'
import {
  ACT_TOOL_NAMES,
  isPendingApproval,
  isSaveToolName,
  parseResult,
} from './proposals'
import { Settings, ArrowRight, Check, ArrowDown } from '../ui/icons'

// Display only. The approve/cancel action lives in ApprovalBar pinned above
// the input, so it is always the last thing shown (chronological).
export default function ToolCallRow({ entry }: { entry: ToolCallEntry }) {
  const isSaveTool = isSaveToolName(entry.name)
  const isActTool = ACT_TOOL_NAMES.has(entry.name)
  const safeInput = entry.input ?? {}
  const parsed = parseResult(entry.result)
  const isToolError = parsed?.status === 'error'

  return (
    <Disclosure
      className="my-1 text-xs"
      defaultOpen={isSaveTool || isActTool}
      summary={
        <span className="flex items-center gap-2 text-fg-muted">
          <Settings size={14} />
          <span className="font-mono">{entry.name}</span>
        </span>
      }
    >
      <div className="p-3 space-y-2">
        {/* Content preview */}
        {entry.name === 'save_workflow' &&
        (parsed?.content ?? safeInput.content) ? (
          <CodeBlock
            lang="yaml"
            code={(parsed?.content ?? safeInput.content) as string}
          />
        ) : entry.name === 'save_plugin' && (parsed?.code ?? safeInput.code) ? (
          <CodeBlock
            lang="python"
            code={(parsed?.code ?? safeInput.code) as string}
          />
        ) : isActTool ? (
          parsed?.preview ? (
            <pre className="text-fg-muted whitespace-pre-wrap break-words">
              {JSON.stringify(parsed.preview, null, 2)}
            </pre>
          ) : null
        ) : !isSaveTool ? (
          <pre className="text-fg whitespace-pre-wrap break-words">
            {JSON.stringify(entry.input, null, 2)}
          </pre>
        ) : null}

        {/* Resolved outcome (persisted, survives reload) */}
        {entry.outcome === 'approved' && (
          <div className="flex items-center gap-1 mt-2 rounded-md px-2 py-1 bg-success-subtle text-success">
            {entry.name === 'save_workflow' && (
              <Link
                to="/workflows"
                className="inline-flex items-center gap-1 underline mr-2"
              >
                View in Workflows <ArrowRight size={12} />
              </Link>
            )}
            <Check size={12} /> {entry.outcomeLabel ?? 'Done'}
          </div>
        )}
        {entry.outcome === 'cancelled' && (
          <div className="mt-2 rounded-md px-2 py-1 bg-canvas-subtle text-fg-subtle border border-border">
            Cancelled
          </div>
        )}
        {entry.outcome === 'error' && (
          <div className="mt-2 rounded-md px-2 py-1 bg-danger-subtle text-danger">
            {entry.outcomeLabel}
          </div>
        )}

        {/* Awaiting resolution — the buttons are in the bar below the messages */}
        {isPendingApproval(entry) && (
          <div className="flex items-center gap-1 mt-2 text-attention">
            Awaiting your approval below <ArrowDown size={12} />
          </div>
        )}

        {/* Validation error from the AI tool (status === 'error') */}
        {isToolError && (
          <div className="mt-2 rounded-md px-2 py-1 bg-danger-subtle text-danger">
            {parsed?.message ?? entry.result}
          </div>
        )}

        {/* Read-only tool results (raw). Act/save tools render status above. */}
        {!isSaveTool && !isActTool && entry.result && (
          <div className="mt-2 text-fg-muted">{entry.result}</div>
        )}
      </div>
    </Disclosure>
  )
}
