import type { MoveKind, MoveTarget } from '../../../api/db'

/** What the person has chosen on the first step of "Move database". */
export interface Destination {
  kind: MoveKind
  host: string
  port: string
  database: string
  user: string
  password: string
  url: string
  /** Paste a connection URL instead of filling in the fields. */
  useUrl: boolean
}

export const EMPTY_DESTINATION: Destination = {
  kind: 'docker',
  host: 'localhost',
  port: '5432',
  database: '',
  user: '',
  password: '',
  url: '',
  useUrl: false,
}

/** The request body for a destination. */
export function toTarget(d: Destination): MoveTarget {
  if (d.kind !== 'postgres') return { kind: d.kind }
  if (d.useUrl) return { kind: 'postgres', url: d.url.trim() }
  return {
    kind: 'postgres',
    host: d.host.trim(),
    port: Number(d.port) || 5432,
    database: d.database.trim(),
    user: d.user.trim() || null,
    password: d.password || null,
  }
}

/** Whether enough has been filled in to go on. */
export function destinationReady(d: Destination): boolean {
  if (d.kind !== 'postgres') return true
  return d.useUrl
    ? d.url.trim() !== ''
    : d.host.trim() !== '' && d.database.trim() !== ''
}
