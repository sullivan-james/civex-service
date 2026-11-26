import { Button, DataTable, FormError, ProgressBar } from '../ui'
import {
  MAX_PROBLEMS,
  problemsByRow,
  type Choices,
  type Totals,
} from './importPlan'

/** What importing would do, worked out by the server on the real rows with
 * nothing kept: how many are added, changed or not saved, the first rows with
 * the ones that won't work marked, and why each of those won't. */
export function ReviewStep({
  choices,
  checking,
  totals,
  error,
  onBack,
  onImport,
}: {
  choices: Choices
  /** The row the check has got to while it runs; null when it isn't running. */
  checking: { next: number } | null
  totals: Totals | null
  error: string | null
  onBack: () => void
  onImport: () => void
}) {
  const { sheet } = choices
  const byRow = totals ? problemsByRow(totals.problems) : new Map()
  const toSave = totals ? totals.created + totals.updated : 0
  return (
    <div className="space-y-6">
      <h2 className="text-base font-semibold text-fg">Check</h2>

      {checking && (
        <div className="space-y-2" role="status">
          <ProgressBar
            label="Rows checked"
            className="w-full max-w-xl"
            fraction={sheet.total > 0 ? checking.next / sheet.total : 0}
          />
          <p className="text-sm text-fg-muted">
            Checking {checking.next.toLocaleString()} of{' '}
            {sheet.total.toLocaleString()} rows…
          </p>
        </div>
      )}

      <FormError message={error} />

      {totals && (
        <>
          <dl className="flex flex-wrap gap-6 text-sm">
            <Count label="To add" value={totals.created} />
            <Count label="To change" value={totals.updated} />
            <Count label="Already there" value={totals.unchanged} />
            <Count label="Not saved" value={totals.skipped} warn />
          </dl>

          <DataTable
            layout="auto"
            dense
            getRowId={(r) => String(r.number)}
            rows={sheet.rows.map((row, i) => ({
              number: i + 2, // the sheet's own row: the headings are row 1
              row,
            }))}
            rowClassName={(r) =>
              byRow.has(r.number) ? 'bg-danger-subtle' : ''
            }
            columns={[
              { key: 'row', header: 'Row', render: (r) => r.number },
              ...sheet.columns.map((c, j) => ({
                key: c.heading,
                header: c.label,
                render: (r: { row: string[] }) => r.row[j],
              })),
              {
                key: 'why',
                header: '',
                render: (r) => (
                  <span className="text-danger">
                    {byRow.get(r.number) ?? ''}
                  </span>
                ),
              },
            ]}
          />

          {totals.problems.length > 0 && (
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-fg">
                Rows that won't be saved
              </h3>
              <ul className="space-y-0.5 text-sm text-danger">
                {totals.problems.slice(0, 50).map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
              {totals.skipped > Math.min(totals.problems.length, 50) && (
                <p className="text-sm text-fg-muted">
                  And{' '}
                  {(
                    totals.skipped - Math.min(totals.problems.length, 50)
                  ).toLocaleString()}{' '}
                  more
                  {totals.problems.length >= MAX_PROBLEMS
                    ? ' that are not listed'
                    : ''}
                  .
                </p>
              )}
            </div>
          )}
        </>
      )}

      <div className="flex items-center gap-2">
        <Button onClick={onBack}>Back</Button>
        <Button
          variant="primary"
          onClick={onImport}
          disabled={!totals || toSave === 0 || !!checking}
        >
          {totals && toSave > 0
            ? `Import ${toSave.toLocaleString()} rows`
            : 'Import'}
        </Button>
        {totals && toSave === 0 && (
          <span className="text-sm text-fg-muted">
            There is nothing to add.
          </span>
        )}
      </div>
    </div>
  )
}

function Count({
  label,
  value,
  warn = false,
}: {
  label: string
  value: number
  warn?: boolean
}) {
  return (
    <div>
      <dt className="text-fg-muted">{label}</dt>
      <dd
        className={`text-lg font-semibold ${warn && value > 0 ? 'text-danger' : 'text-fg'}`}
      >
        {value.toLocaleString()}
      </dd>
    </div>
  )
}
