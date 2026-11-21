import { api } from './client'
import type { RecordSelectionBody } from './records'

/** Whether a record needs a check or has been checked; `none` clears it. */
export type ReviewStatus = 'none' | 'needs_check' | 'checked'

/** A record's review: its status, who set it and when. */
export interface ReviewValue {
  status: Exclude<ReviewStatus, 'none'>
  by: string | null
  at: string
}

export interface ReviewResult {
  status: ReviewStatus
  records: number
  changed: number
  unchanged: number
}

/** A note left on a record. */
export interface Note {
  id: string
  record_id: string
  body: string
  author: string | null
  created_at: string
  edited_at: string | null
  resolved_at: string | null
  resolved_by: string | null
  deleted_at: string | null
}

export interface OpenNotes {
  notes: number
  records: number
}

export const reviewApi = {
  /** Mark the chosen records; `dry_run` only counts. */
  setReview: (
    body: RecordSelectionBody & { status: ReviewStatus; dry_run?: boolean },
  ) => api.post<ReviewResult>('/records/review', body),

  openNotes: (body: RecordSelectionBody) =>
    api.post<OpenNotes>('/records/open-notes', body),

  notes: (recordId: string) =>
    api.get<Note[]>(`/records/${encodeURIComponent(recordId)}/notes`),

  addNote: (recordId: string, body: string) =>
    api.post<Note>(`/records/${encodeURIComponent(recordId)}/notes`, { body }),

  editNote: (id: string, body: string) =>
    api.patch<Note>(`/notes/${encodeURIComponent(id)}`, { body }),

  resolveNote: (id: string, resolved: boolean) =>
    api.post<Note>(`/notes/${encodeURIComponent(id)}/resolve`, { resolved }),

  deleteNote: (id: string) =>
    api.delete<Note>(`/notes/${encodeURIComponent(id)}`),

  restoreNote: (id: string) =>
    api.post<Note>(`/notes/${encodeURIComponent(id)}/restore`, {}),
}
