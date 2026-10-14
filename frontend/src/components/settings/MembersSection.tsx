import { useCollections } from '../../hooks/useCollections'
import { useAccount, useMe } from '../../hooks/useMe'
import { ACTIONS, whereAllowed, type Action } from '../../utils/permissions'
import { Button, Card, Skeleton } from '../ui'
import { ExternalLink } from '../ui/icons'

/** Settings → Members & access, under a host that has accounts: who you are
 * here and what you may do, from `GET /me`. Who else is a member, and their
 * roles, are the host's to manage on its own pages (`manage_url`), so this
 * links there rather than keeping a second copy. */
export default function MembersSection() {
  const me = useMe()
  const account = useAccount()
  const { data: collections } = useCollections()
  if (!me) return <Skeleton className="h-32 w-full max-w-2xl" />
  const names = new Map((collections ?? []).map((c) => [c.id, c.name]))
  const words = { ...ACTIONS, ...me.permissions.all }
  const actions = Object.keys(words) as Action[]
  const allowed = actions.filter((a) => me.permissions.actions[a]?.length)
  const refused = actions.filter((a) => !me.permissions.actions[a]?.length)
  return (
    <div className="max-w-2xl space-y-5">
      <Card
        title={`You are signed in as ${account.name}`}
        action={
          account.manage_url && (
            <Button href={account.manage_url} size="sm">
              Members and roles <ExternalLink size={14} aria-hidden="true" />
            </Button>
          )
        }
      >
        <dl className="space-y-3 text-sm">
          {allowed.map((action) => (
            <div key={action}>
              <dt className="text-fg">You may {words[action]}</dt>
              <dd className="text-fg-muted">
                {whereAllowed(me.permissions.actions[action] ?? [], names)}
              </dd>
            </div>
          ))}
        </dl>
        {refused.length > 0 && (
          <p className="mt-4 text-sm text-fg-muted">
            You may not {refused.map((a) => words[a]).join('; ')}. Ask someone
            who manages this project’s members.
          </p>
        )}
      </Card>
    </div>
  )
}
