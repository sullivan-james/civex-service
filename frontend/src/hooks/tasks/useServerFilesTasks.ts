import { Download, Upload } from '../../components/ui/icons'
import type { FilesWaiting, RemoteStatus } from '../../api/remote'
import type { BackgroundTask } from '../../utils/backgroundTasks'
import { describeSyncProgress } from '../../utils/syncProgress'
import { formatSize } from '../../utils/storage'
import { useFileListing } from '../useFileListing'
import {
  useIgnoreMissingFiles,
  useRemoteStatus,
  useSendFilesNow,
  useUpdateRemote,
} from '../useRemote'

/** Every collection's files, as the explorer lists them, narrowed. */
export const ALL_FILES = '/collections?tab=records&show=files'
const UNSENT = `${ALL_FILES}&files.server=unsent`
const MISSING = `${ALL_FILES}&files.place=missing`

/** Files and the server, as tasks of their own: files move apart from
 * syncing (a sync carries records only), so they are shown apart too. A bar
 * while files go up or come down; otherwise how many files this computer made
 * that aren't on the server yet and why, with **Send now** only when some can
 * go; and, apart, files cited by records that came from the server and that
 * the server hasn't got (the device that added them hasn't uploaded them: not
 * this computer's to send). One offer to keep every file, for a computer that
 * fetches files only when they are opened. */
export function useServerFilesTasks(): BackgroundTask[] {
  const { data } = useRemoteStatus()
  const sendNow = useSendFilesNow()
  const ignore = useIgnoreMissingFiles()
  const update = useUpdateRemote()
  const offered =
    !!data &&
    data.configured &&
    !data.serving &&
    data.download_files === 'opened' &&
    (data.files_not_here ?? 0) > 0
  // How big they are, once the listing has said (it can take a moment).
  const sizes = useFileListing({ limit: 1 }, offered)
  const bytes = sizes.data?.summary
    .filter((p) => p.kind === 'server')
    .reduce((n, p) => n + p.bytes, 0)
  return data
    ? serverFilesTasks(
        data,
        { disabled: sendNow.isPending, onClick: () => sendNow.mutate() },
        { disabled: ignore.isPending, onClick: () => ignore.mutate() },
        {
          disabled: update.isPending,
          bytes,
          onClick: () => update.mutate({ download_files: 'all' }),
        },
      )
    : []
}

export function serverFilesTasks(
  data: RemoteStatus,
  send: { disabled: boolean; onClick: () => void },
  ignore?: { disabled: boolean; onClick: () => void },
  keepAll?: { disabled: boolean; onClick: () => void; bytes?: number },
): BackgroundTask[] {
  if (!data.configured) return []
  const tasks: BackgroundTask[] = []
  const waiting = data.files_waiting
  // While the project is still being copied, the file counts cover only the
  // records copied so far: said once the copy is done.
  const copying = !!data.connecting || data.progress?.phase === 'copying'

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

  const arriving = copying ? 0 : (data.files_arriving ?? 0)
  if (arriving > 0)
    tasks.push({
      id: 'server-files-arriving',
      tone: 'info',
      icon: Upload,
      title: `${plural(arriving, 'file')} ${arriving === 1 ? 'isn’t' : 'aren’t'} on the server yet`,
      detail: `The device that added ${arriving === 1 ? 'it hasn’t uploaded it' : 'them hasn’t uploaded them'}.`,
      actions: [{ label: 'See which', to: MISSING }],
    })
  const lacked = copying ? 0 : (data.files_missing ?? 0)
  if (lacked > 0)
    tasks.push({
      id: 'server-files-lacked',
      tone: 'attention',
      icon: Upload,
      title: `${plural(lacked, 'file')} missing`,
      detail: `The device that added ${lacked === 1 ? 'it' : 'them'} never uploaded ${lacked === 1 ? 'it' : 'them'}.`,
      actions: [{ label: 'See which', to: MISSING }],
    })

  const missing = waiting?.missing ?? 0
  if (missing > 0)
    tasks.push({
      id: 'server-files-missing',
      tone: 'attention',
      icon: Upload,
      title: `${plural(missing, 'file')} missing`,
      detail: `${missing === 1 ? 'It is' : 'They are'} no longer on this computer, and the server hasn’t got ${missing === 1 ? 'it' : 'them'}.`,
      actions: [
        { label: 'See which', to: MISSING },
        // Only files this project never stored can be ignored; ones stored
        // once and since gone stay in the warning.
        ...(ignore && (waiting?.never_stored ?? 0) > 0
          ? [{ label: 'Ignore', ...ignore }]
          : []),
      ],
    })

  const notHere = data.files_not_here ?? 0
  if (
    keepAll &&
    !copying &&
    !data.serving &&
    data.download_files === 'opened' &&
    notHere > 0 &&
    !data.files_progress
  ) {
    const size = keepAll.bytes ? `, ${formatSize(keepAll.bytes)}` : ''
    tasks.push({
      id: 'download-all-files',
      tone: 'info',
      icon: Download,
      title: 'Files download when opened',
      actions: [
        {
          label: `Download all files (${plural(notHere, 'file')}${size})`,
          variant: 'primary',
          disabled: keepAll.disabled,
          onClick: keepAll.onClick,
        },
      ],
    })
  }
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
