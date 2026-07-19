import type { StoredSession } from '../../types/ai'

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
  onDelete: (id: string, e: React.MouseEvent) => void
  onNewChat: () => void
}) {
  return (
    <div className="flex-1 overflow-y-auto flex flex-col min-h-0">
      <div className="p-3 border-b border-[#d0d7de] flex-shrink-0">
        <button
          onClick={onNewChat}
          className="w-full py-1.5 rounded-md bg-[#0969da] text-white text-sm font-medium hover:bg-[#0860ca] transition-colors"
        >
          + New chat
        </button>
      </div>
      {sessions.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-xs text-[#adbac7]">
          No saved sessions yet
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto divide-y divide-[#eaeef2]">
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => onRestore(s)}
              className="w-full text-left px-4 py-3 hover:bg-[#f6f8fa] transition-colors group"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm text-[#1f2328] truncate flex-1">
                  {s.title}
                </p>
                <span
                  role="button"
                  onClick={(e) =>
                    onDelete(s.id, e as unknown as React.MouseEvent)
                  }
                  className="text-[#d0d7de] hover:text-[#d1242f] transition-colors opacity-0 group-hover:opacity-100 flex-shrink-0 cursor-pointer"
                  title="Delete session"
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 16 16"
                    fill="currentColor"
                  >
                    <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
                  </svg>
                </span>
              </div>
              <p className="text-[10px] text-[#adbac7] mt-0.5">
                {relativeTime(s.createdAt)}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
