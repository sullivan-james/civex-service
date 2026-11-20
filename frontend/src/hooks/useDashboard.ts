import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { dashboardApi, type DashboardCard } from '../api/dashboard'

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
  if (card.view) out.view = card.view
  if (card.widget) out.widget = card.widget
  return out
}
