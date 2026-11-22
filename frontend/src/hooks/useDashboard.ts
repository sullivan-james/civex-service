import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  dashboardApi,
  type CardRecords,
  type DashboardCard,
} from '../api/dashboard'
import type { Chart } from '../api/schemas'
import { useToast } from '../components/ui/ToastProvider'
import { errorMessage } from '../lib/errors'
import { newChartId, storedChart } from '../utils/charts'

/** The Analytics page's cards, shared by everyone in the project. */
export function useDashboard() {
  return useQuery({ queryKey: ['dashboard'], queryFn: dashboardApi.get })
}

/** Save the page's cards (the whole list, in order). */
export function useSaveDashboard() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (cards: DashboardCard[]) => dashboardApi.save(cards),
    onSuccess: (page) => qc.setQueryData(['dashboard'], page),
  })
}

/** A card as it is saved: what the page keeps, without what it shows. */
export function storedCard(card: DashboardCard): DashboardCard {
  const out: DashboardCard = { id: card.id, kind: card.kind, size: card.size }
  if (card.title) out.title = card.title
  if (card.chart && card.records) {
    out.chart = storedChart({ ...card.chart, id: card.id })
    const r = card.records
    out.records = { schema: r.schema }
    if (r.collection) out.records.collection = r.collection
    if (r.within) out.records.within = r.within
    if (r.search) out.records.search = r.search
    if (r.filter) out.records.filter = r.filter
  }
  if (card.widget) out.widget = card.widget
  return out
}

/** **Add to Analytics page**: put a chart, with the records it counts now,
 * at the end of the page (read fresh, so nobody else's edit is lost). */
export function useAddToAnalytics() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: async (card: {
      chart: Chart
      title: string
      records: CardRecords
    }) => {
      const page = await dashboardApi.get()
      return dashboardApi.save([
        ...page.cards.map(storedCard),
        storedCard({
          id: newChartId(),
          kind: 'chart',
          size: 'small',
          title: card.title,
          chart: card.chart,
          records: card.records,
        }),
      ])
    },
    onSuccess: (page) => {
      qc.setQueryData(['dashboard'], page)
      toast.success('Added to Analytics')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
}
