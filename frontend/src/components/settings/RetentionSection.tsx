import { useState } from 'react'
import {
  useRetentionSettings,
  useSetRetention,
} from '../../hooks/useUISettings'
import type { RetentionRequest } from '../../api/retention'
import type { RetentionSettings } from '../../api/settings'
import {
  Button,
  Checkbox,
  ConfirmDialog,
  Field,
  Input,
  Skeleton,
  Subheading,
  InfoTip,
} from '../ui'
import {
  useForgetPurgedHistory,
  usePurgedHistory,
} from '../../hooks/useRetention'
import { RetentionCleanUpDialog } from './RetentionCleanUpDialog'

/** A period in days, or forever when the box is ticked. */
function KeepFor({
  label,
  foreverLabel,
  info,
  forever,
  days,
  onForever,
  onDays,
}: {
  label: string
  foreverLabel: string
  info: string
  forever: boolean
  days: string
  onForever: (forever: boolean) => void
  onDays: (days: string) => void
}) {
  const invalid =
    !forever && !(Number.isInteger(Number(days)) && Number(days) >= 1)
  return (
    <div className="flex flex-wrap items-end gap-4">
      <Field label={label} info={info}>
        <Input
          type="number"
          min={1}
          className="w-28"
          value={days}
          disabled={forever}
          invalid={invalid}
          onChange={(e) => onDays(e.target.value)}
          aria-label={`${label}, days`}
        />
      </Field>
      <Field label={foreverLabel} layout="inline">
        <Checkbox
          checked={forever}
          onChange={(e) => onForever(e.target.checked)}
        />
      </Field>
    </div>
  )
}

const asDays = (value: number | null) => (value ? String(value) : '90')
const toNumber = (forever: boolean, days: string) =>
  forever ? null : Number(days)

function RetentionForm({ settings }: { settings: RetentionSettings }) {
  const save = useSetRetention()
  const [restorable, setRestorable] = useState(
    String(settings.purge_after_days),
  )
  const [auto, setAuto] = useState(settings.auto_purge_deleted)
  const [auditForever, setAuditForever] = useState(settings.audit_days === null)
  const [auditDays, setAuditDays] = useState(asDays(settings.audit_days))
  const [runsForever, setRunsForever] = useState(settings.run_days === null)
  const [runDays, setRunDays] = useState(asDays(settings.run_days))

  const valid =
    Number.isInteger(Number(restorable)) &&
    Number(restorable) >= 1 &&
    (auditForever ||
      (Number.isInteger(Number(auditDays)) && Number(auditDays) >= 1)) &&
    (runsForever || (Number.isInteger(Number(runDays)) && Number(runDays) >= 1))
  const next: RetentionSettings = {
    purge_after_days: Number(restorable),
    auto_purge_deleted: auto,
    audit_days: toNumber(auditForever, auditDays),
    run_days: toNumber(runsForever, runDays),
  }
  const dirty = JSON.stringify(next) !== JSON.stringify(settings)

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <Subheading>Deleted items</Subheading>
        <div className="flex flex-wrap items-end gap-4">
          <Field
            label="Restorable for (days)"
            info="How long a deleted collection, schema or record can be restored."
          >
            <Input
              type="number"
              min={1}
              className="w-28"
              value={restorable}
              onChange={(e) => setRestorable(e.target.value)}
            />
          </Field>
          <Field
            label="Delete them for good when cleaning up"
            info="Off: deleted items stay until you delete them. On: a clean-up permanently deletes whatever was deleted longer ago than this."
            layout="inline"
          >
            <Checkbox
              checked={auto}
              onChange={(e) => setAuto(e.target.checked)}
            />
          </Field>
        </div>
      </div>

      <div className="space-y-3">
        <Subheading>Change history</Subheading>
        <KeepFor
          label="Keep history for (days)"
          foreverLabel="Keep history forever"
          info="Older entries are removed by a clean-up, except those about things that can still be restored."
          forever={auditForever}
          days={auditDays}
          onForever={setAuditForever}
          onDays={setAuditDays}
        />
      </div>

      <div className="space-y-3">
        <Subheading>Workflow runs and logs</Subheading>
        <KeepFor
          label="Keep runs and logs for (days)"
          foreverLabel="Keep runs and logs forever"
          info="Finished runs and their step logs older than this are removed by a clean-up. A run that is waiting or running is never removed."
          forever={runsForever}
          days={runDays}
          onForever={setRunsForever}
          onDays={setRunDays}
        />
      </div>

      <Button
        size="sm"
        disabled={!valid || !dirty || save.isPending}
        onClick={() => save.mutate(next)}
      >
        {save.isPending ? 'Saving…' : 'Save'}
      </Button>
    </div>
  )
}

const startOfDay = (date: string) =>
  date ? new Date(`${date}T00:00:00`).toISOString() : null

function CleanUp({ settings }: { settings: RetentionSettings }) {
  const [request, setRequest] = useState<RetentionRequest | null>(null)
  const [deleted, setDeleted] = useState('')
  const [history, setHistory] = useState('')
  const [runs, setRuns] = useState('')
  const hasSettings =
    settings.auto_purge_deleted ||
    settings.audit_days !== null ||
    settings.run_days !== null

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <Subheading>Apply these settings</Subheading>
        <Button
          size="sm"
          disabled={!hasSettings}
          onClick={() => setRequest({ from_settings: true })}
        >
          Clean up now…
        </Button>
        {!hasSettings && (
          <p className="text-xs text-fg-muted">
            Everything is kept forever, so there is nothing to apply.
          </p>
        )}
      </div>

      <div className="space-y-3">
        <Subheading>Delete everything before a date</Subheading>
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Deleted items, deleted before">
            <Input
              type="date"
              value={deleted}
              onChange={(e) => setDeleted(e.target.value)}
            />
          </Field>
          <Field label="Change history before">
            <Input
              type="date"
              value={history}
              onChange={(e) => setHistory(e.target.value)}
            />
          </Field>
          <Field label="Workflow runs before">
            <Input
              type="date"
              value={runs}
              onChange={(e) => setRuns(e.target.value)}
            />
          </Field>
          <Button
            size="sm"
            variant="danger"
            disabled={!deleted && !history && !runs}
            onClick={() =>
              setRequest({
                deleted_before: startOfDay(deleted),
                audit_before: startOfDay(history),
                runs_before: startOfDay(runs),
              })
            }
          >
            Preview…
          </Button>
        </div>
      </div>

      {request && (
        <RetentionCleanUpDialog
          request={request}
          onClose={() => setRequest(null)}
        />
      )}
    </div>
  )
}

/** Records permanently deleted before that also removed their history: their
 * entries are deleted, leaving one tombstone each. Shown only when there are
 * any, which is never once permanent deletes clean up after themselves. */
function PurgedHistory() {
  const { data } = usePurgedHistory()
  const [confirming, setConfirming] = useState(false)
  const forget = useForgetPurgedHistory(() => setConfirming(false))
  if (!data || data.entries === 0) return null
  return (
    <div className="space-y-2">
      <Subheading>History of permanently deleted records</Subheading>
      <p className="text-sm text-fg-muted">
        {data.entries.toLocaleString()} history{' '}
        {data.entries === 1 ? 'entry still holds' : 'entries still hold'} the
        values of records that were permanently deleted.
        <InfoTip>
          Permanently deleting a record now removes its history and leaves only
          a note that it was deleted.
        </InfoTip>
      </p>
      <Button size="sm" variant="danger" onClick={() => setConfirming(true)}>
        Delete that history…
      </Button>
      {confirming && (
        <ConfirmDialog
          title="Delete history of deleted records"
          body={`Delete ${data.entries.toLocaleString()} history entries about records that no longer exist? Each record keeps a single note that it was permanently deleted. This cannot be undone.`}
          confirmLabel="Delete history"
          variant="danger"
          typedConfirmationValue="delete"
          isPending={forget.isPending}
          onConfirm={() => forget.mutate()}
          onClose={() => setConfirming(false)}
        />
      )}
    </div>
  )
}

export default function RetentionSection() {
  const { data: settings, isLoading } = useRetentionSettings()
  if (isLoading || !settings) return <Skeleton className="h-9 w-40" />
  return (
    <div className="space-y-8">
      <RetentionForm key={JSON.stringify(settings)} settings={settings} />
      <hr className="border-border" />
      <CleanUp settings={settings} />
      <PurgedHistory />
    </div>
  )
}
