import { useState } from 'react'
import type { Release } from '../api/releases'
import { CreateReleaseDialog } from '../components/releases/CreateReleaseDialog'
import {
  Badge,
  Button,
  DataTable,
  ListToolbar,
  Page,
  Pagination,
  type DataTableColumn,
} from '../components/ui'
import { useListParams } from '../hooks/useListParams'
import { usePermissions } from '../hooks/useMe'
import { useReleases } from '../hooks/useReleases'
import { errorMessage } from '../lib/errors'

const releaseHref = (r: Pick<Release, 'name'>) =>
  `/releases/${encodeURIComponent(r.name)}`

/** Every release, newest first, with a search held in the address; New
 * release opens the dialog that plans before it makes. */
export default function ReleasesPage() {
  const { data, isLoading, error } = useReleases()
  const list = useListParams('', ['state'])
  const { can, why } = usePermissions()
  const [creating, setCreating] = useState(false)

  const wanted = list.q.trim().toLowerCase()
  const matching = (data ?? []).filter(
    (r) =>
      (!wanted ||
        r.name.toLowerCase().includes(wanted) ||
        r.title.toLowerCase().includes(wanted)) &&
      (!list.picks.state ||
        (list.picks.state === 'withdrawn') === !!r.withdrawn_at),
  )
  const shown = matching.slice(
    list.page * list.size,
    (list.page + 1) * list.size,
  )

  const columns: DataTableColumn<Release>[] = [
    {
      key: 'name',
      header: 'Version',
      render: (r) => (
        <span className="font-medium text-fg">
          {r.name}{' '}
          {r.withdrawn_at && <Badge variant="attention">Withdrawn</Badge>}
        </span>
      ),
    },
    { key: 'title', header: 'Title', render: (r) => r.title },
    {
      key: 'records',
      header: 'Records',
      align: 'right',
      render: (r) => Number(r.counts.records ?? 0).toLocaleString(),
    },
    {
      key: 'made',
      header: 'Made',
      render: (r) => new Date(r.created_at).toLocaleDateString(),
    },
  ]

  return (
    <Page
      title="Releases"
      info="A release is a frozen copy of the data with a version, a citation and a content hash, so a paper can say exactly which data it used and the data can be read back later, however the project has moved on."
      action={
        <Button
          variant="primary"
          onClick={() => setCreating(true)}
          disabled={!can('change_structure')}
          title={can('change_structure') ? undefined : why('change_structure')}
        >
          New release
        </Button>
      }
    >
      <div className="space-y-3">
        <ListToolbar
          search={{
            value: list.q,
            label: 'Search releases',
            onChange: (q) => list.set({ q }),
          }}
          picks={[
            {
              label: 'Show',
              value: list.picks.state,
              options: [
                { value: '', label: 'Every release' },
                { value: 'current', label: 'Not withdrawn' },
                { value: 'withdrawn', label: 'Withdrawn' },
              ],
              onChange: (state) => list.set({ state }),
            },
          ]}
        />
        <DataTable
          dense
          layout="auto"
          columns={columns}
          rows={shown}
          getRowId={(r) => r.id}
          isLoading={isLoading}
          error={error ? errorMessage(error) : undefined}
          rowHref={releaseHref}
          emptyTitle={
            list.q || list.picks.state ? 'No releases match' : 'No releases yet'
          }
          emptyMessage="Make one when the data is ready to cite: it freezes a copy that never changes."
        />
        <Pagination
          page={list.page}
          pageSize={list.size}
          total={matching.length}
          onPage={(page) => list.set({ page })}
          onPageSize={(size) => list.set({ size })}
        />
      </div>
      {creating && <CreateReleaseDialog onClose={() => setCreating(false)} />}
    </Page>
  )
}
