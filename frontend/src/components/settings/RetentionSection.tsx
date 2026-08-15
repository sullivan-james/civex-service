import { useState } from 'react'
import { Link } from 'react-router'
import {
  useRetentionSettings,
  useSetRetention,
} from '../../hooks/useUISettings'
import type { RetentionSettings } from '../../api/settings'
import { Button, Field, Input, Skeleton } from '../ui'

function RetentionForm({ settings }: { settings: RetentionSettings }) {
  const setRetention = useSetRetention()
  const [days, setDays] = useState(String(settings.purge_after_days))

  const parsed = Number(days)
  const isValid = Number.isInteger(parsed) && parsed >= 1
  const isDirty = String(settings.purge_after_days) !== days

  return (
    <div className="flex items-end gap-2">
      <Field label="Purge after (days)" span={undefined}>
        <Input
          type="number"
          min={1}
          className="w-24"
          value={days}
          onChange={(e) => setDays(e.target.value)}
          invalid={!isValid}
        />
      </Field>
      <Button
        variant="default"
        size="sm"
        disabled={!isValid || !isDirty || setRetention.isPending}
        onClick={() => setRetention.mutate(parsed)}
      >
        {setRetention.isPending ? 'Saving…' : 'Save'}
      </Button>
    </div>
  )
}

export default function RetentionSection() {
  const { data: settings, isLoading } = useRetentionSettings()

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold text-fg">Recently Deleted</h2>
        <p className="text-sm text-fg-muted mt-0.5">
          Deleted schemas, collections and records are kept in{' '}
          <Link to="/trash" className="text-accent hover:underline">
            Recently Deleted
          </Link>{' '}
          and can be restored until they're permanently purged.
        </p>
      </div>

      {isLoading || !settings ? (
        <Skeleton className="h-9 w-40" />
      ) : (
        <RetentionForm key={settings.purge_after_days} settings={settings} />
      )}
    </div>
  )
}
