import { useState } from 'react'
import { filesApi } from '../../api/files'
import { importsApi, type ImportSheet } from '../../api/imports'
import { errorMessage } from '../../lib/errors'
import { FileDropZone, FormError, ProgressBar } from '../ui'

/** Choose the spreadsheet: it is sent to the server as it is (CSV, TSV or
 * Excel), with progress, and read there; nothing is held in the page. */
export function FileStep({
  collectionId,
  onRead,
}: {
  /** The collection the file is for; none when it is not chosen yet. */
  collectionId?: string
  onRead: (sheet: ImportSheet, filename: string, sha256: string) => void
}) {
  const [busy, setBusy] = useState<
    { name: string; fraction: number; saving: boolean } | 'reading' | null
  >(null)
  const [error, setError] = useState<string | null>(null)

  async function choose(files: File[]) {
    const file = files[0]
    if (!file) return
    setError(null)
    try {
      setBusy({ name: file.name, fraction: 0, saving: false })
      const sent = await filesApi.uploadBatch(
        [file],
        (info) =>
          setBusy({
            name: file.name,
            fraction: info.total > 0 ? info.loaded / info.total : 0,
            saving: info.saving,
          }),
        collectionId,
      )
      if (sent.stopped || sent.files.length === 0)
        throw new Error(sent.stopped?.message ?? 'The file was not received.')
      setBusy('reading')
      const ref = sent.files[0]
      const read = await importsApi.inspect(ref.sha256, file.name)
      onRead(read, file.name, ref.sha256)
    } catch (e) {
      setError(errorMessage(e))
      setBusy(null)
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-base font-semibold text-fg">Choose a spreadsheet</h2>
      {busy === null ? (
        <FileDropZone
          onFiles={(files) => void choose(files)}
          accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls"
          inputLabel="Spreadsheet file"
        >
          Drop a spreadsheet here, or choose one. CSV or Excel.
        </FileDropZone>
      ) : busy === 'reading' ? (
        <p className="text-sm text-fg-muted" role="status">
          Reading the file…
        </p>
      ) : (
        <div className="space-y-2" role="status">
          <p className="text-sm text-fg">{busy.name}</p>
          <ProgressBar
            label="Sending the file"
            className="w-full max-w-xl"
            fraction={busy.fraction}
            busy={busy.saving}
          />
          <p className="text-sm text-fg-muted">
            {busy.saving ? 'Saving the file…' : 'Sending the file…'}
          </p>
        </div>
      )}
      <FormError message={error} />
    </div>
  )
}
