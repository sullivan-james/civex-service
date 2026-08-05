const BASE = '/api'

/** Some endpoints (e.g. PUT /workflows/{stem}, CIVEX-109) send structured
 * data as `detail` rather than a plain string. `.detail` carries that raw
 * value so callers who know its shape can use it directly; `.message`
 * stays a human-readable fallback for callers that just display text. */
export class ApiError extends Error {
  detail: unknown

  constructor(detail: unknown, status: number) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`)
    this.name = 'ApiError'
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(body.detail, res.status)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  /** Multipart file upload — does NOT set Content-Type (browser sets it with boundary). */
  upload: <T>(path: string, form: FormData) =>
    request<T>(path, { method: 'POST', body: form, headers: {} }),
}
