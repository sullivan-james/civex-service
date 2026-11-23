import { useEffect } from 'react'
import { useLocation } from 'react-router'
import { announceNavigation } from '../utils/navigation'

/** Tells the host (`civex:navigate`, `utils/navigation`) where the app is, on
 * first render and on each route change. */
export function useNavigationEvents(): void {
  const { pathname, search } = useLocation()
  useEffect(() => {
    announceNavigation(pathname + search)
  }, [pathname, search])
}
