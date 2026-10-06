import type { TableFormat } from '../api/fileAccess'

/** The formats a table can be made in, as a person chooses between them: what it
 * is called and what it is for. The first is the default. */
export const TABLE_FORMATS: {
  id: TableFormat
  name: string
  hint: string
}[] = [
  { id: 'csv', name: 'CSV', hint: 'Opens anywhere, in any spreadsheet.' },
  { id: 'xlsx', name: 'Excel', hint: 'A spreadsheet with a header row.' },
  { id: 'tsv', name: 'TSV', hint: 'Like CSV, separated by tabs.' },
  { id: 'json', name: 'JSON', hint: 'For programs; joined values nest.' },
  {
    id: 'jsonl',
    name: 'JSON Lines',
    hint: 'One record per line, for large tables.',
  },
]

export const TABLE_FORMAT_NAME: Record<TableFormat, string> =
  Object.fromEntries(TABLE_FORMATS.map((f) => [f.id, f.name])) as Record<
    TableFormat,
    string
  >
