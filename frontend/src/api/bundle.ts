import { api } from './client'
import { apiUrl } from '../utils/host'

/** What a bundle would hold (`GET /bundle/plan`): the counts the download
 * will have, and how big the files are. */
export interface BundlePlan {
  schemas: number
  collections: string[]
  records: number
  files: number
  file_bytes: number
  files_unreachable: number
  workflows: number
  plugins: number
  include_files: boolean
}

export interface BundleSkipped {
  id: string
  reason: string
}

export interface BundleImportResult {
  schemas_new: number
  schemas_existing: string[]
  collections_new: number
  collections_existing: string[]
  records_added: number
  records_existing: number
  records_skipped: number
  skipped: BundleSkipped[]
  files_added: number
  files_missing: number
  files_refused: number
  workflows: number
  plugins: number
  members_skipped: BundleSkipped[]
}

export interface BundleOptions {
  files: boolean
  collections?: string[]
}

function query(options: BundleOptions): string {
  const params = new URLSearchParams()
  if (!options.files) params.set('files', 'false')
  for (const c of options.collections ?? []) params.append('collection', c)
  const s = params.toString()
  return s ? `?${s}` : ''
}

export const bundleApi = {
  plan: (options: BundleOptions) =>
    api.get<BundlePlan>(`/bundle/plan${query(options)}`),

  /** Starts the browser download of the bundle. */
  download(options: BundleOptions): void {
    const a = document.createElement('a')
    a.href = apiUrl(`/bundle${query(options)}`)
    a.download = 'civex-bundle.civex.zip'
    a.click()
  },

  async import(file: File): Promise<BundleImportResult> {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(apiUrl('/bundle/import'), {
      method: 'POST',
      body: form,
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? `HTTP ${res.status}`)
    }
    return res.json()
  },
}
