import { useState } from 'react'
import { Button, Field, Input } from '../../ui'
import { useTestConnection } from '../../../hooks/useDb'
import type { MoveKind } from '../../../api/db'
import { destinationReady, toTarget, type Destination } from './destination'

const OPTIONS: { kind: MoveKind; title: string; blurb: string }[] = [
  {
    kind: 'docker',
    title: 'Docker PostgreSQL',
    blurb:
      'Civex starts and looks after a PostgreSQL container for this project. Best for large projects. Needs Docker.',
  },
  {
    kind: 'postgres',
    title: 'PostgreSQL server',
    blurb: 'A PostgreSQL server you already run, on this machine or elsewhere.',
  },
  {
    kind: 'sqlite',
    title: 'SQLite file',
    blurb:
      'A single file in your project folder. Simple, and fine for smaller projects.',
  },
]

export function DestinationStep({
  value,
  onChange,
}: {
  value: Destination
  onChange: (next: Destination) => void
}) {
  const check = useTestConnection()
  const [touchedPort, setTouchedPort] = useState(false)

  function set(patch: Partial<Destination>) {
    check.reset() // a result for the old details says nothing about these
    onChange({ ...value, ...patch })
  }

  return (
    <div className="space-y-4">
      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold text-fg mb-2">
          Where should your data go?
        </legend>
        {OPTIONS.map((o) => (
          <label
            key={o.kind}
            className={`flex items-start gap-3 rounded-md border p-3 cursor-pointer ${
              value.kind === o.kind
                ? 'border-accent bg-accent-subtle'
                : 'border-border bg-canvas hover:bg-canvas-subtle'
            }`}
          >
            <input
              type="radio"
              name="move-destination"
              className="mt-1"
              checked={value.kind === o.kind}
              onChange={() => set({ kind: o.kind })}
            />
            <span>
              <span className="block text-sm font-medium text-fg">
                {o.title}
              </span>
              <span className="block text-xs text-fg-muted mt-0.5">
                {o.blurb}
              </span>
            </span>
          </label>
        ))}
      </fieldset>

      {value.kind === 'postgres' && (
        <div className="rounded-md border border-border bg-canvas p-3 space-y-3">
          {value.useUrl ? (
            <Field
              label="Connection URL"
              hint="For example postgresql+psycopg2://user:password@host:5432/dbname"
            >
              <Input
                className="w-full font-mono"
                value={value.url}
                onChange={(e) => set({ url: e.target.value })}
              />
            </Field>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-6 gap-3">
              <div className="sm:col-span-4">
                <Field label="Host">
                  <Input
                    className="w-full"
                    value={value.host}
                    onChange={(e) => set({ host: e.target.value })}
                  />
                </Field>
              </div>
              <div className="sm:col-span-2">
                <Field label="Port">
                  <Input
                    className="w-full"
                    inputMode="numeric"
                    value={value.port}
                    onChange={(e) => {
                      setTouchedPort(true)
                      set({ port: e.target.value.replace(/\D/g, '') })
                    }}
                    aria-invalid={touchedPort && value.port === ''}
                  />
                </Field>
              </div>
              <div className="sm:col-span-6">
                <Field
                  label="Database"
                  hint="It must already exist on the server, and be empty."
                >
                  <Input
                    className="w-full"
                    value={value.database}
                    onChange={(e) => set({ database: e.target.value })}
                  />
                </Field>
              </div>
              <div className="sm:col-span-3">
                <Field label="User">
                  <Input
                    className="w-full"
                    value={value.user}
                    autoComplete="off"
                    onChange={(e) => set({ user: e.target.value })}
                  />
                </Field>
              </div>
              <div className="sm:col-span-3">
                <Field label="Password">
                  <Input
                    className="w-full"
                    type="password"
                    value={value.password}
                    autoComplete="new-password"
                    onChange={(e) => set({ password: e.target.value })}
                  />
                </Field>
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              size="sm"
              disabled={!destinationReady(value) || check.isPending}
              onClick={() => check.mutate(toTarget(value))}
            >
              {check.isPending ? 'Checking…' : 'Check connection'}
            </Button>
            <Button
              size="sm"
              variant="link"
              onClick={() => set({ useUrl: !value.useUrl })}
            >
              {value.useUrl ? 'Use separate fields' : 'Paste a URL'}
            </Button>
          </div>
          {check.data && (
            <p
              role="status"
              className={`text-xs ${check.data.ok ? 'text-success' : 'text-danger'}`}
            >
              {check.data.ok ? 'Connected.' : check.data.error}
            </p>
          )}
          {check.error && (
            <p role="alert" className="text-xs text-danger">
              Couldn&rsquo;t check the connection.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
