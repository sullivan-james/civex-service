import { Upload } from '../../components/ui/icons'
import type { FilesWaiting, RemoteStatus } from '../../api/remote'
import type { BackgroundTask } from '../../utils/backgroundTasks'
import { describeSyncProgress } from '../../utils/syncProgress'
import { useRemoteStatus, useSendFilesNow } from '../useRemote'

/** Every collection's files, as the explorer lists them, narrowed. */
export const ALL_FILES = '/collections?tab=records&show=files'
const UNSENT = `${ALL_FILES}&files.server=unsent`
const MISSING = `${ALL_FILES}&files.place=missing`

/** Files and the server, as tasks of their own: files move apart from
 * syncing (a sync carries records only), so they are shown apart too. A bar
 * while files go up or come down; otherwise how many files here aren't on the
 * server yet and why, with **Send now** only when some can go; and, apart,
 * files that are missing (on no drive here, and the server hasn't got them),
 * which nothing here can send. */
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
  const tasks: BackgroundTask[] = []
  const waiting = data.files_waiting

  if (data.files_progress) {
    const text = describeSyncProgress(data.files_progress)
    tasks.push({
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
      actions: [{ label: 'See files', to: UNSENT }],
    })
  } else if (data.files_to_send > 0) {
    const canGo = waiting ? waiting.ready > 0 : true
    tasks.push({
      id: 'server-files',
      tone: canGo ? 'info' : 'attention',
      icon: Upload,
      title: `${plural(data.files_to_send, 'file')} to send to the server`,
      detail: waiting
        ? whyWaiting(waiting)
        : 'Other computers can’t open them yet. They go up in the background.',
      actions: [
        ...(canGo ? [{ label: 'Send now', ...send }] : []),
        { label: 'See files', to: UNSENT },
      ],
    })
  }

  const missing = waiting?.missing ?? 0
  if (missing > 0)
    tasks.push({
      id: 'server-files-missing',
      tone: 'attention',
      icon: Upload,
      title: `${plural(missing, 'file')} missing`,
      detail: `${missing === 1 ? 'It isn’t' : 'They aren’t'} on this computer, and the server hasn’t got ${missing === 1 ? 'it' : 'them'}, so nothing here can send ${missing === 1 ? 'it' : 'them'}.`,
      actions: [{ label: 'See which', to: MISSING }],
    })
  return tasks
}

/** Why files here haven't gone, in sentences: what will go by itself, and
 * what is on a drive that can't be read (in the drive's own words). */
export function whyWaiting(w: FilesWaiting): string {
  const parts: string[] = []
  if (w.ready > 0)
    parts.push(`${plural(w.ready, 'file')} will go up in the background.`)
  for (const d of w.offline)
    parts.push(
      `${plural(d.files, 'file')} ${d.files === 1 ? 'is' : 'are'} on the drive “${d.volume}”, which can’t be read${d.reason ? ` (${d.reason})` : ''}; ${d.files === 1 ? 'it goes' : 'they go'} once it is plugged in.`,
    )
  return parts.join(' ')
}

function plural(n: number, what: string): string {
  return `${n.toLocaleString()} ${what}${n === 1 ? '' : 's'}`
}
