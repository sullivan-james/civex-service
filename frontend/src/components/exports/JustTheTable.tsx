import type { TableFormat } from '../../api/fileAccess'
import type { Draft } from '../../utils/exportBuilder'
import { TABLE_FORMATS } from '../../utils/tableFormats'
import { Button, Input, Select } from '../ui'
import { Plus, Table } from '../ui/icons'

/** What an export from a list starts as: just the table of what is on screen (its
 * rows and columns, in the order shown), with its format and file name to
 * change, and one way to add more (files, other tables). Most exports from a list
 * want only this, so the rest stays out of the way until it is asked for. */
export function JustTheTable({
  draft,
  set,
  placeholder,
  canAddFiles,
  onMore,
}: {
  draft: Draft
  set: (patch: Partial<Draft>) => void
  /** What the file is called when no name is given, without its extension. */
  placeholder: string
  /** Whether this kind of record, or anything inside it, has files to add. */
  canAddFiles: boolean
  onMore: () => void
}) {
  const [table] = draft.tables
  const change = (patch: Partial<NonNullable<typeof table>>) =>
    set({ tables: [{ ...table, ...patch }] })
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-accent bg-accent-subtle px-4 py-3">
        <Table size={18} className="shrink-0 text-accent" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-base font-medium text-fg">
            The table you’re looking at
          </p>
          <p className="text-sm text-fg-muted">
            The rows and columns shown, in the order shown.
          </p>
        </div>
        <span className="flex flex-wrap items-center gap-2 text-sm text-fg-muted">
          <Select
            size="md"
            value={table.format}
            aria-label="Table format"
            onChange={(e) => change({ format: e.target.value as TableFormat })}
          >
            {TABLE_FORMATS.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </Select>
          named
          <Input
            size="md"
            value={table.name ?? ''}
            placeholder={placeholder}
            aria-label="Table file name"
            className="w-48"
            onChange={(e) => change({ name: e.target.value || null })}
          />
        </span>
      </div>
      <Button size="lg" onClick={onMore}>
        <Plus size={16} aria-hidden />
        {canAddFiles ? 'Add files or more tables…' : 'Add more tables…'}
      </Button>
    </div>
  )
}
