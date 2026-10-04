import type { StoredSession } from '../../types/ai'
import { Button, IconButton, ListButton } from '../ui'
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
        <Button variant="primary" className="w-full" onClick={onNewChat}>
          + New chat
        </Button>
      </div>
      {sessions.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-xs text-fg-subtle">
          No saved sessions yet
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto divide-y divide-border-muted">
          {sessions.map((s) => (
            <div key={s.id} className="relative">
              <ListButton onClick={() => onRestore(s)} className="py-3 pr-12">
                <span className="block truncate text-fg">{s.title}</span>
                <span className="mt-1 block text-xs text-fg-subtle">
                  {relativeTime(s.createdAt)}
                </span>
              </ListButton>
              <IconButton
                icon={Trash2}
                variant="danger"
                className="absolute right-2 top-2"
                aria-label={`Delete session: ${s.title}`}
                onClick={(e) => onDelete(s.id, e)}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
