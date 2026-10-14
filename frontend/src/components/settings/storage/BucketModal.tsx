import { useState } from 'react'
import type {
  BucketCheck,
  BucketSettings,
  BucketStatus,
} from '../../../api/bucket'
import { useCheckBucket, useUseBucket } from '../../../hooks/useBucket'
import { errorMessage } from '../../../lib/errors'
import {
  Button,
  Checkbox,
  Field,
  FormError,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
} from '../../ui'

/** Keep this project's files in a bucket, or change how the one it uses is
 * reached. The server tries the bucket before it saves anything; **Check**
 * tries it without saving. */
export function BucketModal({
  current,
  onClose,
}: {
  /** The bucket in use, when changing how it is reached. */
  current?: BucketStatus
  onClose: () => void
}) {
  const [form, setForm] = useState<Required<BucketSettings>>({
    bucket: current?.bucket ?? '',
    prefix: current?.prefix ?? '',
    region: current?.region ?? '',
    endpoint: current?.endpoint ?? '',
    profile: current?.profile ?? '',
    direct: current?.direct ?? true,
  })
  const [checked, setChecked] = useState<BucketCheck | null>(null)
  const check = useCheckBucket()
  const use = useUseBucket()
  const busy = check.isPending || use.isPending

  function set<K extends keyof BucketSettings>(
    key: K,
    value: BucketSettings[K],
  ) {
    setForm((f) => ({ ...f, [key]: value }))
    setChecked(null)
  }

  const body: BucketSettings = {
    ...form,
    region: form.region || null,
    endpoint: form.endpoint || null,
    profile: form.profile || null,
  }

  return (
    <Modal onClose={onClose} size="lg" dismissible={!busy}>
      <ModalHeader onClose={onClose}>
        {current
          ? 'Change how the bucket is reached'
          : 'Keep files in a bucket'}
      </ModalHeader>
      <ModalBody>
        <div className="space-y-4">
          <p className="text-sm text-fg-muted">
            Works with AWS S3 and anything that speaks its API, such as MinIO or
            Cloudflare R2. Credentials are never saved by civex: it takes them
            from <code>AWS_ACCESS_KEY_ID</code> and{' '}
            <code>AWS_SECRET_ACCESS_KEY</code> where it runs, or from an AWS
            profile.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Bucket" required>
              <Input
                value={form.bucket}
                onChange={(e) => set('bucket', e.target.value)}
                className="font-mono"
                autoFocus
              />
            </Field>
            <Field
              label="Folder in the bucket"
              info="Optional. Lets several projects share one bucket, each in its own folder."
            >
              <Input
                value={form.prefix}
                onChange={(e) => set('prefix', e.target.value)}
                className="font-mono"
              />
            </Field>
            <Field
              label="Endpoint"
              info="Only for a service other than AWS, e.g. http://127.0.0.1:9000 for MinIO on this computer."
            >
              <Input
                value={form.endpoint ?? ''}
                onChange={(e) => set('endpoint', e.target.value)}
                placeholder="AWS"
                className="font-mono"
              />
            </Field>
            <Field label="Region">
              <Input
                value={form.region ?? ''}
                onChange={(e) => set('region', e.target.value)}
                placeholder="The default"
                className="font-mono"
              />
            </Field>
            <Field
              label="AWS profile"
              info="Take credentials from this profile in ~/.aws instead of the environment."
            >
              <Input
                value={form.profile ?? ''}
                onChange={(e) => set('profile', e.target.value)}
                placeholder="None"
                className="font-mono"
              />
            </Field>
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-fg">
            <Checkbox
              checked={form.direct}
              onChange={(e) => set('direct', e.target.checked)}
            />
            Send files straight between browsers or devices and the bucket
          </label>

          {checked && <CheckResult result={checked} />}
          <FormError
            message={
              check.error
                ? errorMessage(check.error)
                : use.error
                  ? errorMessage(use.error)
                  : null
            }
          />
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button
          disabled={!form.bucket.trim() || busy}
          onClick={() =>
            check.mutate(body, { onSuccess: (result) => setChecked(result) })
          }
        >
          {check.isPending ? 'Checking…' : 'Check'}
        </Button>
        <Button
          variant="primary"
          disabled={!form.bucket.trim() || busy || checked?.ok === false}
          onClick={() => use.mutate(body, { onSuccess: onClose })}
        >
          {use.isPending ? 'Checking…' : current ? 'Save' : 'Use this bucket'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}

/** What trying a bucket found, in its own words. */
export function CheckResult({ result }: { result: BucketCheck }) {
  return (
    <div className="space-y-1 text-sm" role="status">
      {result.problems.map((p) => (
        <p key={p} className="text-danger">
          {p}
        </p>
      ))}
      {result.warnings.map((w) => (
        <p key={w} className="text-warning">
          {w}
        </p>
      ))}
      {result.ok && <p className="text-success">The bucket can be used.</p>}
    </div>
  )
}
