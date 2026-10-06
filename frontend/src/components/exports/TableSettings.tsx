import { useState } from 'react'
import type { TableFormat, TableSpec } from '../../api/fileAccess'
import type { Schema } from '../../api/schemas'
import { tableColumnChoices } from '../../utils/exportBuilder'
import { TABLE_FORMATS } from '../../utils/tableFormats'
import { ColumnPicker, type ExtraColumn } from '../views/ColumnPicker'
import { Button, Checkbox, Input, Select } from '../ui'
import { Columns3 } from '../ui/icons'

/** The record's own columns, beside its fields. */
const RECORD_COLUMNS: ExtraColumn[] = [
  { name: 'id', label: 'Record id' },
  { name: 'created_at', label: 'Created' },
  { name: 'updated_at', label: 'Updated' },
]

/** Everything about one ticked table, on its row: its format, what it is called,
 * which columns it has (a panel that opens under the row), and, for a list written
 * in each folder, whether a folder with nothing to list gets one too. Rendered as
 * the children of a `CheckRow`, so it appears only while the table is on. */
export function TableSettings({
  table,
  title,
  placeholder,
  schemas,
  onChange,
}: {
  table: TableSpec
  /** What the table is called in the list, for naming its controls. */
  title: string
  /** What the file is called when no name is given, without its extension. */
  placeholder: string
  schemas: Schema[]
  onChange: (patch: Partial<TableSpec>) => void
}) {
  const [open, setOpen] = useState(false)
  const kind = table.kind ?? ''
  // Columns are chosen for one kind of record; a table of each kind taken has
  // each kind's own, so there is nothing to choose.
  const choices = kind ? tableColumnChoices(schemas, kind) : null
  const everything = choices
    ? ['id', ...choices.baseFields.map((f) => f.name)]
    : []
  const columns = table.columns ?? null
  const list = !!table.where && (table.shape ?? 'rows') === 'rows'

  return (
    <>
      <span className="flex flex-wrap items-center gap-2 text-sm text-fg-muted">
        <Select
          size="sm"
          value={table.format}
          aria-label={`${title}: format`}
          onChange={(e) => onChange({ format: e.target.value as TableFormat })}
        >
          {TABLE_FORMATS.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </Select>
        named
        <Input
          size="sm"
          value={table.name ?? ''}
          placeholder={placeholder}
          aria-label={`${title}: file name`}
          className="w-44"
          onChange={(e) => onChange({ name: e.target.value || null })}
        />
        {choices && (
          <Button
            size="sm"
            aria-expanded={open}
            aria-label={`${title}: columns`}
            onClick={() => setOpen((o) => !o)}
          >
            <Columns3 size={14} aria-hidden />
            {columns ? `${columns.length} columns` : 'All columns'}
          </Button>
        )}
      </span>
      {list && (
        <label className="flex w-full items-center gap-2 text-xs text-fg-muted">
          <Checkbox
            checked={table.skip_empty === false}
            aria-label={`${title}: also where there is nothing to list`}
            onChange={(e) => onChange({ skip_empty: !e.target.checked })}
          />
          Also make one in folders with nothing to list (just its header)
        </label>
      )}
      {choices && open && (
        <div className="w-full space-y-2 pt-1">
          <ColumnPicker
            columns={columns ?? everything}
            onChange={(next) => onChange({ columns: next })}
            baseFields={choices.baseFields}
            joinable={choices.joinable}
            extra={RECORD_COLUMNS}
          />
          {columns?.length === 0 && (
            <p role="alert" className="text-sm text-danger">
              Choose at least one column.
            </p>
          )}
          {columns && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onChange({ columns: null })}
            >
              Use every column
            </Button>
          )}
        </div>
      )}
    </>
  )
}
