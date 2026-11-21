import { api } from './client'
import type { View } from './views'

/** A card on the Analytics page (civex/domain/dashboard.py): a saved analysis
 * (a view with a summary, by id) or a built-in widget, half the page wide or
 * all of it, with an optional title of its own. */
export interface DashboardCard {
  id: string
  kind: 'analysis' | 'widget'
  size: 'small' | 'wide'
  title?: string | null
  view?: string | null
  widget?: string | null
}

export interface DashboardCardShown extends DashboardCard {
  /** The saved view an analysis card names; null once it was deleted. */
  analysis?: View | null
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
