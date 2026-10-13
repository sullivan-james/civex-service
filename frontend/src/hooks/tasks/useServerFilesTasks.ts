import { Upload } from '../../components/ui/icons'
import type { FilesWaiting, RemoteStatus } from '../../api/remote'
import type { BackgroundTask } from '../../utils/backgroundTasks'
import { describeSyncProgress } from '../../utils/syncProgress'
import { useRemoteStatus, useSendFilesNow } from '../useRemote'

const DETAILS = '/settings/sync'

/** Files and the server, as a task of their own: files move apart from
 * syncing (a sync carries records only), so they are shown apart too. A bar
 * while files go up or come down; otherwise, when files here aren't on the
 * server, how many and why, with **Send now** only when some can go. */
export function useServerFilesTasks(): BackgroundTask[] {
  const { data } = useRemoteStatus()
  const sendNow = useSendFilesNow()
  return data
    ? serverFilesTasks(data, {
        disabled: sendNow.isPending,
        onClick: () => sendNow.mutate(),
      })
    : []
}

export function serverFilesTasks(
  data: RemoteStatus,
  send: { disabled: boolean; onClick: () => void },
): BackgroundTask[] {
  if (!data.configured) return []
  const details = { label: 'Details', to: DETAILS }

  if (data.files_progress) {
    const text = describeSyncProgress(data.files_progress)
    return [
      {
        id: 'server-files',
        tone: 'info',
        icon: Upload,
        spinning: true,
        title: text.title,
        progress:
          text.fraction != null
            ? { fraction: text.fraction, label: text.title, count: text.count }
            : undefined,
        detail: text.fraction != null ? undefined : text.detail,
        actions: [details],
      },
    ]
  }

  if (data.files_to_send <= 0) return []
  const waiting = data.files_waiting
  const canGo = waiting ? waiting.ready > 0 : true
  return [
    {
      id: 'server-files',
      tone: canGo ? 'info' : 'attention',
      icon: Upload,
      title: `${plural(data.files_to_send, 'file')} not on the server yet`,
      detail: waiting
        ? whyWaiting(waiting)
        : 'Other computers can’t open them yet. They go up in the background.',
      actions: canGo ? [{ label: 'Send now', ...send }, details] : [details],
    },
  ]
}

/** Why files haven't gone, in sentences: what will go by itself, what is on a
 * drive that can't be read (in the drive's own words), and what isn't on this
 * computer at all. */
export function whyWaiting(w: FilesWaiting): string {
  const parts: string[] = []
  if (w.ready > 0)
    parts.push(`${plural(w.ready, 'file')} will go up in the background.`)
  for (const d of w.offline)
    parts.push(
      `${plural(d.files, 'file')} ${d.files === 1 ? 'is' : 'are'} on the drive “${d.volume}”, which can’t be read${d.reason ? ` (${d.reason})` : ''}; ${d.files === 1 ? 'it goes' : 'they go'} once it is plugged in.`,
    )
  if (w.not_here > 0)
    parts.push(
      `${plural(w.not_here, 'file')} ${w.not_here === 1 ? 'isn’t' : 'aren’t'} on this computer, and the server hasn’t got ${w.not_here === 1 ? 'it' : 'them'} either: a computer that has ${w.not_here === 1 ? 'it' : 'them'} must send ${w.not_here === 1 ? 'it' : 'them'}.`,
    )
  return parts.join(' ')
}

function plural(n: number, what: string): string {
  return `${n.toLocaleString()} ${what}${n === 1 ? '' : 's'}`
}
