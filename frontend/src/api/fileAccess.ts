import { api, ApiError } from './client'
import type { RecordQueryParams, SortEntry } from './query'
import type { FilterTreeWire } from '../utils/filterTree'
import type { FilesLayout } from './views'

/** The formats a table can be made in, with what each is for. */
export type TableFormat = 'csv' | 'xlsx' | 'tsv' | 'json' | 'jsonl'

/** A table made beside the files (or instead of them). Three choices say what it
 * is: its rows (`kind`), where it is written (`where`) and its columns. Leave
 * `kind` out for one table per kind of record the export holds, at the top. */
export interface TableSpec {
  format: TableFormat
  /** Field names, `ref.field` joins or record columns; none = id and every field. */
  columns?: string[] | null
  /** The file's name without its extension. With `kind` it may use `{schema}`,
   * `{id}` and the folder's record fields; none names it for what it holds. */
  name?: string | null
  /** The schema whose records are the rows; none = one table for each kind held. */
  kind?: string | null
  /** A schema: write the table in the folder of each record of it (holding the
   * `kind` records that are that record or beneath it). None = once, at the top. */
  where?: string | null
  /** `rows`: a row per record. `fields`: one record's fields as field/value
   * pairs (needs `where` = `kind`). */
  shape?: 'rows' | 'fields'
  /** false also writes a table in a folder with no rows. */
  skip_empty?: boolean
}

/** Which files: the records a query selects, or exactly `record_ids` (rows the
 * person ticked). Mirrors `FileSelectionRequest` in the server. */
export interface FileSelection {
  collection?: string
  schema_name?: string
  /** Paths start below this record; its descendants' files are included. */
  within?: string
  filter?: FilterTreeWire
  where?: string[]
  search?: string
  record_ids?: string[]
  fields?: string[]
  /** tree: a folder per record above each file (the default); flat: all in
   * one folder. A saved view carries its own. */
  layout?: FilesLayout
  /** A saved view as `schema/view`: its filter, file columns and layout are the
   * selection. */
  view?: string
  /** An export saved with a schema, as `schema/name`: its kind, fields, filter
   * and layout, run in `collection` and/or within the record `within`. */
  export?: string
  /** Only records of these kinds (schema names), when no one kind is named. */
  kinds?: string[]
  /** Also the files of every record beneath each selected one. */
  below?: boolean
  /** Also make these tables. */
  tables?: TableSpec[]
  /** false takes the table alone, with no files (needs `table`). */
  files?: boolean
  /** The order of the records, so of the table's rows. */
  sort?: SortEntry[]
}

/** One table an export would make. */
export interface PlannedTable {
  name: string
  /** The folder it is written in ('' = the top). */
  folder: string
  /** Where it is in the export. */
  path: string
  kind: string
  rows: number
  columns: string[]
  format: TableFormat
  shape: 'rows' | 'fields'
}

/** What's on one drive that can't be reached right now. */
export interface UnavailableGroup {
  /** null: not recorded on any drive this project knows. */
  volume: string | null
  state: string
  reason: string
  fix: string
  files: number
  bytes: number
  /** Names of some of the records affected. */
  records: string[]
}

/** How much of a selection one drive holds. */
export interface VolumeShare {
  volume: string
  files: number
  bytes: number
}

/** What a selection holds and how much can be reached, without the file list. */
export interface FilePlanSummary {
  total: number
  available: number
  bytes: number
  available_bytes: number
  complete: boolean
  /** The reachable files are on more than one drive, so one linked folder
   * can't hold them. */
  scattered: boolean
  /** The one drive a linked folder would go on; null if scattered or empty. */
  link_volume: string | null
  by_volume: VolumeShare[]
  summary: string
  unavailable: UnavailableGroup[]
  /** The tables the selection asks for, beside the files. */
  tables: PlannedTable[]
  /** Files only on the server: downloaded first, so not counted as out of
   * reach. */
  to_fetch?: { files: number; bytes: number }
}

/** One file in a preview: where it would go in the folder, and where it is. */
export interface PlannedFile {
  path: string
  size: number
  available: boolean
  volume: string | null
}

export interface FilePreview extends FilePlanSummary {
  items: PlannedFile[]
}

export type ExportMode = 'link' | 'copy'

export interface ExportOptions {
  /** Tag the request so its progress can be followed (see `progress`). */
  progressId?: string
  name: string
  mode: ExportMode
  /** For a copy: the drive to copy onto (the project folder if left out). */
  volume?: string
  allowPartial: boolean
  open: boolean
}

/** Why an export didn't just happen: the files can't be reached, or are on
 * several drives (so no one linked folder can hold them), or the drive can't
 * link. The server builds nothing in these cases, and says why. */
export interface ExportProblem {
  kind: 'problem'
  code: 'files_unavailable' | 'files_scattered' | 'links_not_possible'
  message: string
  /** What the selection holds and where; absent when the server didn't send it. */
  plan?: FilePlanSummary
}

export type ExportOutcome =
  { kind: 'done'; result: FileExportResult } | ExportProblem

const PROBLEM_CODES = [
  'files_unavailable',
  'files_scattered',
  'links_not_possible',
]

/** The refusal an error carries, if it is one the server explains (409 with a
 * known `code`). */
export function problemFrom(err: unknown): ExportProblem | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null
  const code = err.body.code
  if (typeof code !== 'string' || !PROBLEM_CODES.includes(code)) return null
  return {
    kind: 'problem',
    code: code as ExportProblem['code'],
    message: typeof err.detail === 'string' ? err.detail : '',
    plan: err.body.plan as FilePlanSummary | undefined,
  }
}

export interface FileExportResult {
  dest: string
  /** A drive name, or "project". */
  location: string | null
  /** Hard links: the stored file under another name. */
  linked: number
  copied: number
  unchanged: number
  removed: number
  /** Tables written beside the files. */
  tables: number
  missing: { path: string; reason: string }[]
  complete: boolean
  /** The server showed the folder in the file manager. */
  opened: boolean
}

/** An export folder on disk, for cleaning up. */
export interface ExportInfo {
  name: string
  /** A drive name, or "project". */
  location: string
  path: string
  files: number
  /** Space it takes (copies; a link takes none). null: not recorded. */
  bytes_on_disk: number | null
  linked: number | null
  copied: number | null
  updated: string | null
}

export interface RemoveExportsResult {
  results: {
    path: string
    removed_files: number
    freed_bytes: number
    kept_files: number
    folder_removed: boolean
  }[]
  errors: { path: string; error: string }[]
}

/** How far a tagged request has got: the stage, steps done of how many (0 until
 * known), and whether it has finished. */
export interface FileProgress {
  phase: string
  done: number
  total: number
  finished: boolean
  error: string | null
  /** A stage that moves bytes (downloading): so far, of how many, how fast
   * (bytes a second), seconds left. */
  bytes_done?: number
  bytes_total?: number
  rate?: number
  eta?: number | null
}

const PROGRESS_HEADER = 'X-Civex-Progress'

/** The file name a download response carries, if it says. */
function filenameOf(res: Response): string | null {
  const header = res.headers.get('Content-Disposition') ?? ''
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (star) return decodeURIComponent(star[1])
  return /filename="?([^";]+)"?/i.exec(header)?.[1] ?? null
}

/** Headers that tag a request with a progress id (JSON, as every body here is). */
const tagged = (progressId?: string) =>
  progressId
    ? { 'Content-Type': 'application/json', [PROGRESS_HEADER]: progressId }
    : undefined

/** The files-by-name selection for what the explorer is showing: its current
 * query (schema, scope, filter, search), or just the ticked rows. */
export function selectionFor(
  query: RecordQueryParams,
  collection: string | undefined,
  recordIds?: string[],
  layout?: FilesLayout,
  /** Take everything beneath the records too (an Encounter holds none itself). */
  below?: boolean,
): FileSelection {
  if (recordIds && recordIds.length > 0)
    return { collection, record_ids: recordIds, layout, below }
  return {
    collection,
    layout,
    below,
    schema_name: query.schema ?? undefined,
    within: query.within ?? undefined,
    filter: query.filter ?? undefined,
    where: query.where,
    search: query.search || undefined,
  }
}

/** Files picked from a selection: narrowed to a place (a drive's name,
 * `server`, `missing`, or the groups `here` and `unreachable`), a name (the
 * file's or its record's) and ticked content. What the Files tab lists is what
 * its actions act on. */
export interface FilePick extends FileSelection {
  place?: string
  name?: string
  /** Only these files (by content hash): the ticked rows, each with every
   * use of it listed. Records outside the list that use it are not picked. */
  shas?: string[]
  /** Only files used by exactly one of these numbers of live records. */
  used_by?: number[]
  /** Moving: also move files records not picked use (for them too). */
  include_shared?: boolean
}

export type PlaceKind = 'drive' | 'unreachable' | 'server' | 'missing'

/** How much of a selection is in one place. */
export interface PlaceSummary {
  /** A drive's name, or `server` / `missing`. */
  place: string
  kind: PlaceKind
  files: number
  bytes: number
  /** For a drive that can't be read: why, and what to do. */
  reason: string
  fix: string
}

/** One file of a selection, with where it is. */
export interface ListedFile {
  path: string
  sha256: string
  filename: string
  size: number
  record_id: string
  record_name: string
  field: string
  volume: string | null
  state: string
  available: boolean
  reason: string
  fix: string
  place: string
  place_kind: PlaceKind
  /** Records not listed here that use the same file: moving it moves it for
   * them too. */
  others?: number
  /** The records listed here that use this file (one row per file as
   * stored), each with the names of the records above it. */
  uses?: FileUse[]
}

export interface FileUse {
  record_id: string
  record_name: string
  field: string
  /** The name this record gives the file (its own name template). */
  filename: string
  /** The records above it, outermost first, from where the list starts. */
  trail: string[]
}

/** What moving picked files onto a drive would do. */
export interface MovePlan {
  files: number
  bytes: number
  /** Only on the server: downloaded straight onto the drive. */
  from_server: number
  /** Also used by records not picked: they stay unless asked. */
  shared_left: number
  shared_bytes: number
  already_there: number
}

export interface FileListing {
  /** Files matching the place and name. */
  total: number
  /** Every file of the kinds chosen, by place (before narrowing by place). */
  summary: PlaceSummary[]
  items: ListedFile[]
  /** How many files of each kind (file field) the selection holds. */
  kinds?: { field: string; files: number; bytes: number }[]
  /** How many files are used by how many live records (before narrowing by
   * that): the "Used by" pick's choices. */
  sharing?: { records: number; files: number }[]
}

/** What a download from the server did. */
export interface DownloadResult {
  /** Files that came. */
  fetched: number
  /** Listed rows those cover: records that share a file share its download. */
  listed: number
  /** Files the server hasn't got either. */
  absent: number
  /** Where those still are, and what brings them, grouped. */
  absent_where: { reason: string; fix: string; files: number }[]
}

export const fileAccessApi = {
  /** Totals, which drives hold the files, and what's out of reach; makes
   * nothing. */
  plan: (selection: FileSelection, progressId?: string) =>
    api.post<FilePlanSummary>(
      '/file-access/plan',
      { ...selection, include_items: false },
      tagged(progressId),
    ),

  /** How far the request tagged with this id has got. 404 until it has begun. */
  progress: (progressId: string) =>
    api.get<FileProgress>(
      `/file-access/progress/${encodeURIComponent(progressId)}`,
    ),

  /** The plan with its first `limit` files, so a person can see the folder it
   * would make before making it. */
  preview: (selection: FileSelection, limit = 40) =>
    api.post<FilePreview>('/file-access/plan', {
      ...selection,
      include_items: true,
      limit,
    }),

  /** Build the folder on the server's machine (`name` picks which one) and,
   * if the request is from that machine, show it. `link` goes on the drive
   * holding the files; `copy` onto `volume` (the project if left out). */
  export: (selection: FileSelection, options: ExportOptions) =>
    api.post<FileExportResult>(
      '/file-access/export',
      {
        ...selection,
        name: options.name,
        mode: options.mode,
        volume: options.volume,
        allow_partial: options.allowPartial,
        open: options.open,
      },
      tagged(options.progressId),
    ),

  /** The same files and tables, as a zip with the same paths (or the table
   * itself, when that is all there is), with the name the server gave it. */
  zip: async (
    selection: FileSelection,
    allowPartial: boolean,
    progressId?: string,
    name?: string,
  ) => {
    const res = await fetch('/api/file-access/zip', {
      method: 'POST',
      headers: tagged(progressId) ?? { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...selection, allow_partial: allowPartial, name }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new ApiError(body.detail, res.status, body)
    }
    return { blob: await res.blob(), filename: filenameOf(res) }
  },

  /** A page of a selection's files and where all of them are. */
  files: (
    pick: FilePick & { order?: string; offset?: number; limit?: number },
  ) => api.post<FileListing>('/file-access/files', pick),

  /** Bring the picked files that are only on the server to this computer. */
  download: (pick: FilePick, progressId?: string) =>
    api.post<DownloadResult>('/file-access/download', pick, tagged(progressId)),

  /** Remove this computer's copies of the picked files the server holds;
   * `dryRun` only counts. */
  freeUp: (pick: FilePick, dryRun: boolean) =>
    api.post<{
      files: number
      bytes: number
      kept_shared: number
      not_on_server: number
      done: boolean
    }>(`/file-access/free-up?dry_run=${dryRun}`, pick),

  /** Queue a move of just this selection's files onto one drive, so a linked
   * folder can hold them all. Nothing else in their collections moves. */
  /** What moving these files onto `volume` would do; nothing is done. */
  planMove: (pick: FilePick, volume: string, includeShared: boolean) =>
    api.post<{ plan: MovePlan }>('/file-access/gather?dry_run=true', {
      ...pick,
      volume,
      include_shared: includeShared,
    }),

  gather: (selection: FilePick, volume: string, progressId?: string) =>
    api.post<GatherResult>(
      '/file-access/gather',
      { ...selection, volume },
      tagged(progressId),
    ),

  /** `export`, but a refusal the server explains comes back as a value to act on
   * (what is unreachable, which drives hold the files) instead of an error. */
  tryExport: async (
    selection: FileSelection,
    options: ExportOptions,
  ): Promise<ExportOutcome> => {
    try {
      return {
        kind: 'done',
        result: await fileAccessApi.export(selection, options),
      }
    } catch (err) {
      const problem = problemFrom(err)
      if (problem) return problem
      throw err
    }
  },

  listExports: () => api.get<ExportInfo[]>('/file-access/exports'),

  removeExports: (paths: string[]) =>
    api.post<RemoveExportsResult>('/file-access/exports/remove', { paths }),
}

/** What starting a move of a selection's files answers. */
export interface GatherResult {
  /** Null when nothing had to move: the files only on the server were
   * downloaded straight onto the drive (`downloaded`). */
  transfer_id: string | null
  volume: string
  files: number
  bytes: number
  /** How many came from the server straight onto the drive. */
  downloaded?: number
}
