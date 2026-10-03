import { Button, DataTable, FormError } from '../ui'
import { ArrowRight, Upload, Database } from '../ui/icons'
import type { ParsedCsv } from '../../utils/csv'
import type { Mode } from './importWizardTypes'

/** Step 1: pick a source (a folder of files, or a CSV) and load it. */
export function SourceStep({
  mode,
  onModeChange,
  files,
  onFilesChange,
  csvReadError,
  parsedCsv,
  onCsvFileChange,
  sourceValid,
  onContinue,
}: {
  mode: Mode | null
  onModeChange: (mode: Mode) => void
  files: File[]
  onFilesChange: (files: File[]) => void
  csvReadError: string | null
  parsedCsv: ParsedCsv | null
  onCsvFileChange: (file: File | null) => void
  sourceValid: boolean
  onContinue: () => void
}) {
  return (
    <div className="space-y-4">
      <div className="flex gap-3">
        <button
          onClick={() => onModeChange('files')}
          className={`flex-1 flex items-center gap-3 px-4 py-4 rounded-md border text-left transition-colors cursor-pointer ${
            mode === 'files'
              ? 'border-accent bg-accent-subtle'
              : 'border-border hover:border-accent'
          }`}
        >
          <Upload size={18} className="text-accent shrink-0" />
          <span>
            <span className="block text-sm font-medium text-fg">Files</span>
            <span className="block text-xs text-fg-muted">
              A folder of scans, images, recordings…
            </span>
          </span>
        </button>
        <button
          onClick={() => onModeChange('csv')}
          className={`flex-1 flex items-center gap-3 px-4 py-4 rounded-md border text-left transition-colors cursor-pointer ${
            mode === 'csv'
              ? 'border-accent bg-accent-subtle'
              : 'border-border hover:border-accent'
          }`}
        >
          <Database size={18} className="text-accent shrink-0" />
          <span>
            <span className="block text-sm font-medium text-fg">
              Spreadsheet
            </span>
            <span className="block text-xs text-fg-muted">
              A CSV of rows to turn into records
            </span>
          </span>
        </button>
      </div>

      {mode === 'files' && (
        <div className="space-y-2">
          <input
            id="import-files-input"
            type="file"
            multiple
            className="block w-full text-sm text-fg file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-canvas-subtle file:text-fg hover:file:bg-border-muted cursor-pointer"
            onChange={(e) => onFilesChange(Array.from(e.target.files ?? []))}
          />
          {files.length > 0 && (
            <div className="border border-border rounded-md p-3 space-y-1">
              <p className="text-xs font-medium text-fg">
                {files.length} file{files.length === 1 ? '' : 's'} selected
              </p>
              <div className="max-h-40 overflow-y-auto text-xs font-mono text-fg-muted space-y-0.5">
                {files.slice(0, 30).map((f, i) => (
                  <p key={i} className="truncate">
                    {f.name}
                  </p>
                ))}
                {files.length > 30 && <p>… and {files.length - 30} more</p>}
              </div>
            </div>
          )}
        </div>
      )}

      {mode === 'csv' && (
        <div className="space-y-2">
          <input
            type="file"
            accept=".csv,text/csv"
            className="block w-full text-sm text-fg file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-canvas-subtle file:text-fg hover:file:bg-border-muted cursor-pointer"
            onChange={(e) => onCsvFileChange(e.target.files?.[0] ?? null)}
          />
          {csvReadError && <FormError message={csvReadError} />}
          {parsedCsv && parsedCsv.columns.length > 0 && (
            <div className="border border-border rounded-md overflow-hidden">
              <div className="px-3 py-2 text-xs font-medium text-fg bg-canvas-subtle border-b border-border">
                {parsedCsv.columns.length} column
                {parsedCsv.columns.length === 1 ? '' : 's'} ·{' '}
                {parsedCsv.rows.length} row
                {parsedCsv.rows.length === 1 ? '' : 's'}
              </div>
              <DataTable
                layout="auto"
                maxHeight="16rem"
                className="border-0 rounded-none"
                columns={parsedCsv.columns.map((c) => ({
                  key: c,
                  header: c,
                  className: 'whitespace-nowrap',
                  render: (i: number) => parsedCsv.rows[i][c],
                }))}
                rows={parsedCsv.rows.slice(0, 5).map((_, i) => i)}
                getRowId={(i) => String(i)}
              />
            </div>
          )}
          {parsedCsv && parsedCsv.rows.length === 0 && (
            <FormError message="No data rows found in this file." />
          )}
        </div>
      )}

      <div className="flex justify-end">
        <Button
          variant="primary"
          disabled={!mode || !sourceValid}
          onClick={onContinue}
        >
          Continue <ArrowRight size={14} />
        </Button>
      </div>
    </div>
  )
}
