import { useState } from 'react'
import { Link } from 'react-router'
import type { ToolCallEntry } from '../../types/ai'
import CodeBlock from './CodeBlock'
import {
  ACT_TOOL_NAMES,
  isPendingApproval,
  isSaveToolName,
  parseResult,
} from './proposals'

// Display only. The approve/cancel action lives in ApprovalBar pinned above
// the input, so it is always the last thing shown (chronological).
export default function ToolCallRow({ entry }: { entry: ToolCallEntry }) {
  const isSaveTool = isSaveToolName(entry.name)
  const isActTool = ACT_TOOL_NAMES.has(entry.name)
  const [open, setOpen] = useState(isSaveTool || isActTool)
  const safeInput = entry.input ?? {}
  const parsed = parseResult(entry.result)
  const isToolError = parsed?.status === 'error'

  return (
    <div className="my-1 rounded-lg border border-[#d0d7de] bg-[#f6f8fa] text-xs overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left text-[#656d76] hover:bg-[#eaeef2] transition-colors"
      >
        <span>⚙</span>
        <span className="font-mono">{entry.name}</span>
        <span className="ml-auto text-[#adbac7]">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-[#d0d7de] p-3 space-y-2">
          {/* Content preview */}
          {entry.name === 'save_workflow' &&
          (parsed?.content ?? safeInput.content) ? (
            <CodeBlock
              lang="yaml"
              code={(parsed?.content ?? safeInput.content) as string}
            />
          ) : entry.name === 'save_plugin' &&
            (parsed?.code ?? safeInput.code) ? (
            <CodeBlock
              lang="python"
              code={(parsed?.code ?? safeInput.code) as string}
            />
          ) : isActTool ? (
            parsed?.preview ? (
              <pre className="text-[#656d76] whitespace-pre-wrap break-words">
                {JSON.stringify(parsed.preview, null, 2)}
              </pre>
            ) : null
          ) : !isSaveTool ? (
            <pre className="text-[#1f2328] whitespace-pre-wrap break-words">
              {JSON.stringify(entry.input, null, 2)}
            </pre>
          ) : null}

          {/* Resolved outcome (persisted, survives reload) */}
          {entry.outcome === 'approved' && (
            <div className="mt-2 rounded-md px-2 py-1 bg-[#dafbe1] text-[#1a7f37]">
              {entry.name === 'save_workflow' && (
                <Link to="/workflows" className="underline mr-2">
                  View in Workflows →
                </Link>
              )}
              ✓ {entry.outcomeLabel ?? 'Done'}
            </div>
          )}
          {entry.outcome === 'cancelled' && (
            <div className="mt-2 rounded-md px-2 py-1 bg-[#f6f8fa] text-[#adbac7] border border-[#d0d7de]">
              Cancelled
            </div>
          )}
          {entry.outcome === 'error' && (
            <div className="mt-2 rounded-md px-2 py-1 bg-[#ffebe9] text-[#d1242f]">
              {entry.outcomeLabel}
            </div>
          )}

          {/* Awaiting resolution — the buttons are in the bar below the messages */}
          {isPendingApproval(entry) && (
            <div className="mt-2 text-[#9a6700]">
              Awaiting your approval below ↓
            </div>
          )}

          {/* Validation error from the AI tool (status === 'error') */}
          {isToolError && (
            <div className="mt-2 rounded-md px-2 py-1 bg-[#ffebe9] text-[#d1242f]">
              {parsed?.message ?? entry.result}
            </div>
          )}

          {/* Read-only tool results (raw). Act/save tools render status above. */}
          {!isSaveTool && !isActTool && entry.result && (
            <div className="mt-2 text-[#656d76]">{entry.result}</div>
          )}
        </div>
      )}
    </div>
  )
}
