import { api } from './client'
import type { Chart } from './schemas'
import type { FilterTreeWire } from '../utils/filterTree'

/** The records a chart card counts (civex/domain/charts.py `Scope`): a kind
 * and optionally a collection (ids), a record they sit inside, a search and
 * a filter. */
export interface CardRecords {
  schema: string
  collection?: string | null
  within?: string | null
  search?: string | null
  filter?: FilterTreeWire | null
}

/** A card on the Analytics page (civex/domain/dashboard.py): a chart with
 * the records it counts, or a built-in widget; half the page wide or all of
 * it, with an optional title of its own. */
export interface DashboardCard {
  id: string
  kind: 'chart' | 'widget'
  size: 'small' | 'wide'
  title?: string | null
  chart?: Omit<Chart, 'id'> & { id?: string }
  records?: CardRecords | null
  widget?: string | null
}

export interface DashboardCardShown extends DashboardCard {
  /** A chart card's kind and collection by name (null once gone). */
  schema_name?: string | null
  schema_label?: string | null
  collection_name?: string | null
  /** Why the chart can't be drawn any more. */
  problem?: string | null
}

/** The project's one Analytics page, shared by everyone. */
export interface Dashboard {
  cards: DashboardCardShown[]
  /** Whether anyone has changed it yet (until then: every widget). */
  edited: boolean
  /** Every built-in widget, by key, with its name. */
  widgets: Record<string, string>
}

export const dashboardApi = {
  get: () => api.get<Dashboard>('/dashboard'),
  /** Replace the cards (in order): add, remove, reorder and resize at once. */
  save: (cards: DashboardCard[]) => api.put<Dashboard>('/dashboard', { cards }),
}
