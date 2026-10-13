import { ChevronLeft } from 'lucide-react'
import { useAccount } from '../../hooks/useMe'

/** Under a host, which project this is and the way back to the person's
 * projects (`GET /me`'s `account.project` and `home_url`). A local civex has
 * neither, and this draws nothing. */
export function HostProject() {
  const { project, home_url: home } = useAccount()
  if (!project && !home) return null
  return (
    <span className="flex min-w-0 items-center gap-2 text-sm">
      {home && (
        <a
          href={home}
          title="All your projects"
          className="inline-flex shrink-0 items-center gap-0.5 text-nav-fg-muted hover:text-nav-fg hover:underline"
        >
          <ChevronLeft size={14} aria-hidden="true" />
          Projects
        </a>
      )}
      {project && (
        <span className="truncate font-medium text-nav-fg">{project}</span>
      )}
    </span>
  )
}
