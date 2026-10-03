import { useState } from 'react'
import { Link } from 'react-router'
import { useFileInfo } from '../../hooks/useFiles'
import { Badge, Button, Skeleton } from '../ui'
import { Network } from '../ui/icons'
import { errorMessage } from '../../lib/errors'
import { formatSize } from '../../utils/storage'

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button
      size="sm"
      variant="link"
      aria-label={label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        } catch {
          /* clipboard unavailable (insecure context): nothing to do */
        }
      }}
    >
      {copied ? 'Copied' : 'Copy'}
    </Button>
  )
}

/** Where a file's content actually is, and everything that uses it. Opened
 * from a file's location chip in advanced mode. A file is stored once however
 * many records use it, so "used by" is how to see what shares it. */
export function FileInfoPanel({ sha256 }: { sha256: string }) {
  const { data, isLoading, error } = useFileInfo(sha256)

  if (isLoading)
    return (
      <div className="w-96 max-w-full space-y-2 p-3" aria-hidden="true">
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    )
  if (error || !data)
    return (
      <p role="alert" className="w-96 max-w-full p-3 text-xs text-danger">
        {error ? errorMessage(error) : 'Nothing is known about this file.'}
      </p>
    )

  return (
    <div className="w-96 max-w-full space-y-3 p-3 text-xs">
      <section aria-label="Stored on">
        <h3 className="mb-1 font-semibold text-fg">Stored on</h3>
        {data.copies.length === 0 ? (
          <p className="text-attention">
            Not found on any volume. It may only exist on a remote that
            hasn&apos;t been fetched, or the drive holding it hasn&apos;t been
            added.
          </p>
        ) : (
          <ul className="space-y-2">
            {data.copies.map((copy) => (
              <li key={copy.volume} className="space-y-0.5">
                <p className="flex flex-wrap items-center gap-1.5 text-fg">
                  <span className="font-medium">{copy.volume}</span>
                  {copy.network && (
                    <Badge variant="accent">
                      <Network size={10} className="mr-1" aria-hidden="true" />
                      Network
                    </Badge>
                  )}
                  {copy.state !== 'online' && (
                    <Badge variant="danger">
                      {copy.state.replace('_', ' ')}
                    </Badge>
                  )}
                </p>
                <p className="flex items-start gap-2">
                  <span className="min-w-0 break-all font-mono text-fg-muted">
                    {copy.path}
                  </span>
                  <CopyButton
                    text={copy.path}
                    label={`Copy path on ${copy.volume}`}
                  />
                </p>
                {copy.present === null && (
                  <p className="text-attention">
                    Recorded here, but the volume can&apos;t be checked right
                    now.
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
        {data.copies.length > 1 && (
          <p className="mt-1 text-fg-muted">
            The same content is on {data.copies.length} volumes.
          </p>
        )}
      </section>

      <section aria-label="Content">
        <h3 className="mb-1 font-semibold text-fg">Content</h3>
        <p className="flex items-start gap-2">
          <span className="min-w-0 break-all font-mono text-fg-muted">
            {data.sha256}
          </span>
          <CopyButton text={data.sha256} label="Copy hash" />
        </p>
        <p className="text-fg-muted">{formatSize(data.size)}</p>
      </section>

      <section aria-label="Used by">
        <h3 className="mb-1 font-semibold text-fg">Used by</h3>
        <p className="text-fg-muted">
          {data.records} {data.records === 1 ? 'record' : 'records'}
          {data.jobs > 0 &&
            `, ${data.jobs} workflow ${data.jobs === 1 ? 'run' : 'runs'}`}
        </p>
        {data.collections.length > 0 && (
          <ul className="mt-1 space-y-0.5">
            {data.collections.map((c) => (
              <li key={c.id || 'none'} className="text-fg-muted">
                {c.name && c.id ? (
                  <Link
                    to={`/collections/${c.id}`}
                    className="text-accent hover:underline"
                  >
                    {c.name}
                  </Link>
                ) : (
                  <span className="italic">(deleted collection)</span>
                )}{' '}
                · {c.records} {c.records === 1 ? 'record' : 'records'}
              </li>
            ))}
          </ul>
        )}
      </section>

      <Link
        to="/settings/storage"
        className="inline-block text-accent hover:underline"
      >
        Storage settings
      </Link>
    </div>
  )
}
