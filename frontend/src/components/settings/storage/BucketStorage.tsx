import { useState } from 'react'
import type { BucketCheck, BucketStatus } from '../../../api/bucket'
import {
  useBucket,
  useCheckBucket,
  useStopUsingBucket,
} from '../../../hooks/useBucket'
import { errorMessage } from '../../../lib/errors'
import { formatSize } from '../../../utils/storage'
import { Button, Card, ConfirmDialog, FormError, Skeleton } from '../../ui'
import { BucketModal, CheckResult } from './BucketModal'

/** Settings > Storage for a project whose files are in a bucket: where, what
 * it holds, trying it, changing how it is reached, and going back to drives
 * (only while it holds nothing, since files are never moved). */
export function BucketStorage() {
  const { data, isLoading } = useBucket()
  const [editing, setEditing] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [checked, setChecked] = useState<BucketCheck | null>(null)
  const check = useCheckBucket()
  const stop = useStopUsingBucket()

  if (isLoading || !data) return <Skeleton className="h-32" />
  if (!data.bucket) return null

  return (
    <div className="space-y-4">
      <Card
        title="Files are kept in a bucket"
        info="Every file this project stores goes to the bucket. There are no drives to manage, and devices that sync send and fetch files straight to and from it."
        action={
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={check.isPending}
              onClick={() =>
                check.mutate(settingsOf(data), { onSuccess: setChecked })
              }
            >
              {check.isPending ? 'Checking…' : 'Check'}
            </Button>
            <Button size="sm" onClick={() => setEditing(true)}>
              Change…
            </Button>
          </div>
        }
      >
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-fg-muted">Bucket</dt>
          <dd className="font-mono">
            {data.bucket}
            {data.prefix ? `/${data.prefix}` : ''}
          </dd>
          {data.endpoint && (
            <>
              <dt className="text-fg-muted">Endpoint</dt>
              <dd className="font-mono">{data.endpoint}</dd>
            </>
          )}
          {data.region && (
            <>
              <dt className="text-fg-muted">Region</dt>
              <dd className="font-mono">{data.region}</dd>
            </>
          )}
          {data.profile && (
            <>
              <dt className="text-fg-muted">AWS profile</dt>
              <dd className="font-mono">{data.profile}</dd>
            </>
          )}
          <dt className="text-fg-muted">Holds</dt>
          <dd>
            {data.bucket_files.toLocaleString()}{' '}
            {data.bucket_files === 1 ? 'file' : 'files'},{' '}
            {formatSize(data.bucket_bytes)}
          </dd>
          <dt className="text-fg-muted">Files travel</dt>
          <dd>
            {data.direct ? 'Straight to and from the bucket' : 'Through civex'}
          </dd>
        </dl>
        {data.left_on_drives > 0 && (
          <p className="mt-3 text-sm text-warning">
            {data.left_on_drives.toLocaleString()} files are recorded on drives,
            which a project using a bucket can’t reach.
          </p>
        )}
        {checked && (
          <div className="mt-3">
            <CheckResult result={checked} />
          </div>
        )}
        <FormError message={check.error ? errorMessage(check.error) : null} />
      </Card>

      <Card
        title="Keep files on drives instead"
        info="Files are never moved between a bucket and drives, so this is possible only while the bucket holds none of this project’s files."
        action={
          <Button
            size="sm"
            disabled={!data.can_switch}
            title={data.blocked ?? undefined}
            onClick={() => setLeaving(true)}
          >
            Use drives…
          </Button>
        }
      />

      {editing && (
        <BucketModal current={data} onClose={() => setEditing(false)} />
      )}
      {leaving && (
        <ConfirmDialog
          title="Keep files on drives?"
          body="New files will be stored on this computer’s drives. The bucket holds none of this project’s files, so nothing is left behind."
          confirmLabel="Use drives"
          isPending={stop.isPending}
          warning={stop.error ? errorMessage(stop.error) : undefined}
          onConfirm={() =>
            stop.mutate(undefined, { onSuccess: () => setLeaving(false) })
          }
          onClose={() => setLeaving(false)}
        />
      )}
    </div>
  )
}

function settingsOf(s: BucketStatus) {
  return {
    bucket: s.bucket ?? '',
    prefix: s.prefix,
    region: s.region,
    endpoint: s.endpoint,
    profile: s.profile,
    direct: s.direct,
  }
}
