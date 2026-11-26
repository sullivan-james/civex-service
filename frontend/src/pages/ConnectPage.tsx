import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { useCollections } from '../hooks/useCollections'
import { useSchemas } from '../hooks/useSchemas'
import { useConnectRemote, useRemoteStatus } from '../hooks/useRemote'
import { useHasFeature } from '../hooks/useFeatures'
import { errorMessage } from '../lib/errors'
import { approvalUrl, parseHubAddress } from '../utils/hubAddress'
import { describeSyncProgress } from '../utils/syncProgress'
import {
  Button,
  Card,
  Disclosure,
  ErrorState,
  Field,
  Input,
  Page,
  ProgressBar,
  Spinner,
} from '../components/ui'
import { formatTime } from '../utils/dates'

/** Errors that mean the hub said no, not that something broke: the fix is a
 * person there, not trying again. */
const NO_ACCESS = /approved|refused|not allowed|denied|permission|access/i

/** "Connect to a hub": a full page that joins this project to a repository on
 * a host. `?url=` fills the address in (the host's "open in the app" link).
 * It uses the same connect as Settings -> Sync; this page only says what will
 * happen first and then follows it through to the end. */
export default function ConnectPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const dials = useHasFeature()('remote_dial')
  const status = useRemoteStatus()
  const collections = useCollections()
  const schemas = useSchemas()
  const connect = useConnectRemote()
  const [raw, setRaw] = useState(params.get('url') ?? '')
  const [invite, setInvite] = useState('')
  // When connecting began: the status read before that is an old one.
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [target, setTarget] = useState<ReturnType<typeof parseHubAddress>>(null)
  const opened = useRef<string | null>(null)

  const s = startedAt && status.dataUpdatedAt >= startedAt ? status.data : null
  const verify =
    s?.awaiting_approval?.verify_url ?? connect.data?.verify_url ?? null
  const code = s?.awaiting_approval?.code ?? connect.data?.code ?? null
  const approveAt = verify && code ? approvalUrl(verify, code) : null

  // The approval page opens by itself once, as soon as there is a code.
  useEffect(() => {
    if (approveAt && opened.current !== approveAt) {
      opened.current = approveAt
      window.open(approveAt, '_blank', 'noopener')
    }
  }, [approveAt])

  const phase = s?.progress?.phase
  const usable = phase !== 'copying' && phase !== 'filling'
  const done =
    !!s &&
    s.configured &&
    !s.connecting &&
    !s.connect_error &&
    usable &&
    !connect.isPending
  useEffect(() => {
    if (done) navigate('/')
  }, [done, navigate])

  if (!dials)
    return (
      <Page title="Connect to a hub">
        <ErrorState message="This server does not connect to another one." />
      </Page>
    )

  const parsed = parseHubAddress(raw)
  const known = collections.isSuccess && schemas.isSuccess
  const empty =
    (collections.data?.length ?? 0) + (schemas.data?.length ?? 0) === 0
  const name = (target ?? parsed)?.name ?? 'the hub'

  function start() {
    if (!parsed) return
    setTarget(parsed)
    setStartedAt(Date.now())
    connect.mutate({
      url: parsed.address,
      invite: invite.trim() || undefined,
    })
  }

  const busy = startedAt !== null && !connect.isError
  let body
  if (!busy) {
    if (s === null && status.data?.configured && !status.data.connecting) {
      body = (
        <Card title="This project is already connected">
          <p className="text-sm text-fg-muted">
            It follows {status.data.remote}. Disconnect it in Settings → Sync to
            connect to another.
          </p>
          <Button size="sm" className="mt-3" to="/settings/sync">
            Sync settings
          </Button>
        </Card>
      )
    } else {
      body = (
        <div className="max-w-xl space-y-4">
          <Field label="Hub address">
            <Input
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
              placeholder="https://hub.example.com/owner/repo"
              className="font-mono"
              autoFocus={!raw}
            />
          </Field>
          {raw.trim() && !parsed && (
            <p role="alert" className="text-xs text-danger">
              Use a web address, like https://hub.example.com/owner/repo.
            </p>
          )}
          <Disclosure summary="Have an invite code?">
            <Field label="Invite code">
              <Input
                type="password"
                value={invite}
                onChange={(e) => setInvite(e.target.value)}
                autoComplete="off"
              />
            </Field>
          </Disclosure>
          {parsed && known && (
            <p className="text-sm text-fg-muted" data-testid="plan">
              {empty
                ? `This project is empty. It will become a copy of ${parsed.name}.`
                : `This project has data. It can only connect to a repo with nothing in it, and then fills it. If ${parsed.name} has data, nothing changes.`}
            </p>
          )}
          {connect.error && (
            <p role="alert" className="text-sm text-danger">
              {errorMessage(connect.error)}
            </p>
          )}
          <Button disabled={!parsed || !known} onClick={start}>
            Connect
          </Button>
        </div>
      )
    }
  } else if (s?.connect_error) {
    const help = NO_ACCESS.test(s.connect_error)
    body = (
      <Card title="Connecting did not finish">
        <p role="alert" className="text-sm text-attention">
          {s.connect_error}
        </p>
        {help && (
          <p className="mt-2 text-sm text-fg-muted">
            Ask an admin of{' '}
            {target?.page ? (
              <a
                href={target.page}
                target="_blank"
                rel="noreferrer"
                className="text-accent hover:underline"
              >
                {target.name}
              </a>
            ) : (
              name
            )}{' '}
            to let you in, then try again.
          </p>
        )}
        <div className="mt-3 flex gap-2">
          <Button size="sm" onClick={start}>
            Try again
          </Button>
          <Button
            size="sm"
            variant="link"
            onClick={() => {
              setStartedAt(null)
              connect.reset()
            }}
          >
            Change the address
          </Button>
        </div>
      </Card>
    )
  } else if (s?.connecting && s.awaiting_approval) {
    body = (
      <Card title="Approve in your browser">
        <p className="text-sm">
          The hub needs to let this computer in. Check that the page shows this
          code:
        </p>
        <p className="my-3 font-mono text-2xl tracking-wider">
          {s.awaiting_approval.code}
        </p>
        <div className="flex flex-wrap items-center gap-3">
          {approveAt && (
            <Button href={approveAt} target="_blank" rel="noreferrer">
              Approve in your browser
            </Button>
          )}
          <Spinner />
          <span className="text-xs text-fg-muted">
            It carries on by itself once you have approved. The code works until{' '}
            {formatTime(s.awaiting_approval.expires_at * 1000, {
              seconds: false,
            })}
            .
          </span>
        </div>
        {!approveAt && (
          <p className="mt-2 text-xs text-fg-muted">
            Approve this code on {name}, in its devices page.
          </p>
        )}
      </Card>
    )
  } else if (s?.progress) {
    const text = describeSyncProgress(s.progress)
    body = (
      <Card title={text.title}>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {text.fraction != null ? (
            <ProgressBar
              fraction={text.fraction}
              label={text.title}
              className="w-64"
            />
          ) : (
            <Spinner />
          )}
          <span className="text-fg-muted">{text.detail}</span>
        </div>
      </Card>
    )
  } else {
    body = (
      <Card title={`Connecting to ${name}`}>
        <Spinner />
      </Card>
    )
  }

  return (
    <Page title="Connect to a hub" loading={undefined}>
      {body}
    </Page>
  )
}
