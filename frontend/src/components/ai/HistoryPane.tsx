import type { StoredSession } from '../../types/ai'
import { Trash2 } from '../ui/icons'

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

export default function HistoryPane({
  sessions,
  onRestore,
  onDelete,
  onNewChat,
}: {
  sessions: StoredSession[]
  onRestore: (s: StoredSession) => void
  onDelete: (id: string, e: React.MouseEvent | React.KeyboardEvent) => void
  onNewChat: () => void
}) {
  return (
    <div className="flex-1 overflow-y-auto flex flex-col min-h-0">
      <div className="p-3 border-b border-border flex-shrink-0">
        <button
          onClick={onNewChat}
          className="w-full py-2 rounded-md bg-accent text-fg-on-emphasis text-sm font-medium hover:bg-accent-emphasis transition-colors"
        >
          + New chat
        </button>
      </div>
      {sessions.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-xs text-fg-subtle">
          No saved sessions yet
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto divide-y divide-[#eaeef2]">
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => onRestore(s)}
              className="w-full text-left px-4 py-3 hover:bg-canvas-subtle transition-colors group"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm text-fg truncate flex-1">{s.title}</p>
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => onDelete(s.id, e)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onDelete(s.id, e)
                    }
                  }}
                  aria-label={`Delete session: ${s.title}`}
                  className="text-border hover:text-danger transition-colors opacity-0 group-hover:opacity-100 focus-visible:opacity-100 flex-shrink-0 cursor-pointer"
                  title="Delete session"
                >
                  <Trash2 size={12} />
                </span>
              </div>
              <p className="text-xs text-fg-subtle mt-1">
                {relativeTime(s.createdAt)}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
