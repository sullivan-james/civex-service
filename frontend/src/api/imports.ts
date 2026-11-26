import { api } from './client'

/** A column of the spreadsheet, as the server first reads it. */
export interface ImportColumn {
  /** The column as the reader names it: what a choice is keyed by. */
  heading: string
  /** The heading to show ("Column 3" when the sheet has none). */
  label: string
  /** The field key it would become. */
  key: string
  /** What the first rows look like. */
  dtype: string
  /** Blank cells among the first rows. */
  blanks: number
}

export interface ImportSheet {
  filename: string
  /** An Excel file's sheets; none for a text file. */
  sheets: string[]
  sheet: string | null
  columns: ImportColumn[]
  /** The first rows, as text, in column order. */
  rows: string[][]
  /** Rows under the headings, in all. */
  total: number
}

/** What becomes of one column. */
export interface ColumnChoice {
  heading: string
  /** The field it goes in; null leaves the column out. */
  field: string | null
  /** Make the field first. */
  create: boolean
  dtype: string
  label?: string | null
}

export interface ImportRequest {
  sha256: string
  filename: string
  sheet: string | null
  collection: string
  /** Make the collection if it isn't there. */
  new_collection?: boolean
  kind: string
  kind_label: string | null
  columns: ColumnChoice[]
  match_on: string[]
  if_exists: 'update' | 'skip' | 'add_new'
}

export interface ImportBatch {
  start: number
  read: number
  created: number
  updated: number
  unchanged: number
  skipped: number
  /** Why rows were skipped: "Row 5: age: 'abc' is not a whole number". */
  problems: string[]
  done: boolean
}

export const importsApi = {
  inspect: (sha256: string, filename: string, sheet?: string | null) => {
    const q = new URLSearchParams({ sha256, filename })
    if (sheet) q.set('sheet', sheet)
    return api.get<ImportSheet>(`/import/inspect?${q}`)
  },
  /** A part of the file: `check` keeps nothing and says what saving would do.
   * `batch` puts the changes of every part in one event of history. */
  run: (
    request: ImportRequest,
    start: number,
    limit: number,
    check: boolean,
    batch?: string,
  ) =>
    api.post<ImportBatch>(
      '/import/run',
      { ...request, start, limit, check },
      batch
        ? { 'Content-Type': 'application/json', 'X-Civex-Batch': batch }
        : undefined,
    ),
}
