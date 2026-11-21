import { api } from './client'
import type { RecordSelectionBody } from './records'

/** A note left on a record, or a reply in a note's thread. */
export interface Note {
  id: string
  record_id: string
  /** For a reply, the note that starts its thread; null for one that does. */
  thread_id: string | null
  body: string
  author: string | null
  created_at: string
  edited_at: string | null
  /** A thread is resolved as a whole, on the note that starts it. */
  resolved_at: string | null
  resolved_by: string | null
  deleted_at: string | null
  /** A thread's replies, oldest first (on the note that starts it). */
  replies: Note[]
}

export interface OpenNotes {
  /** Open threads (a note and its replies count once). */
  notes: number
  records: number
}

export const notesApi = {
  openNotes: (body: RecordSelectionBody) =>
    api.post<OpenNotes>('/records/open-notes', body),

  /** A record's threads, oldest first, each with its replies. */
  notes: (recordId: string) =>
    api.get<Note[]>(`/records/${encodeURIComponent(recordId)}/notes`),

  addNote: (recordId: string, body: string) =>
    api.post<Note>(`/records/${encodeURIComponent(recordId)}/notes`, { body }),

  /** Reply in the thread `id` is in; a resolved thread opens again. */
  reply: (id: string, body: string) =>
    api.post<Note>(`/notes/${encodeURIComponent(id)}/replies`, { body }),

  editNote: (id: string, body: string) =>
    api.patch<Note>(`/notes/${encodeURIComponent(id)}`, { body }),

  resolveNote: (id: string, resolved: boolean) =>
    api.post<Note>(`/notes/${encodeURIComponent(id)}/resolve`, { resolved }),

  deleteNote: (id: string) =>
    api.delete<Note>(`/notes/${encodeURIComponent(id)}`),

  restoreNote: (id: string) =>
    api.post<Note>(`/notes/${encodeURIComponent(id)}/restore`, {}),
}
