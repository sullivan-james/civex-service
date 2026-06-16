export interface RestoreResult {
  schemas: number
  datasets: number
  records_restored: number
  records_total: number
  workflows: number
  plugins: number
}

export const dumpApi = {
  /** Triggers a browser download of civex-dump.yaml */
  exportDump(noData = false): void {
    const url = `/api/dump${noData ? '?no_data=true' : ''}`
    const a = document.createElement('a')
    a.href = url
    a.download = 'civex-dump.yaml'
    a.click()
  },

  async importDump(file: File): Promise<RestoreResult> {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch('/api/restore', { method: 'POST', body: form })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? `HTTP ${res.status}`)
    }
    return res.json()
  },
}
