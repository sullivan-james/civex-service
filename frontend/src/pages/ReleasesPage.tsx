import type { Release } from '../api/releases'
import {
  Badge,
  DataTable,
  ListToolbar,
  Page,
  Pagination,
  type DataTableColumn,
} from '../components/ui'
import { useListParams } from '../hooks/useListParams'
import { useReleases } from '../hooks/useReleases'
import { errorMessage } from '../lib/errors'

const stateOf = (r: Release) =>
  r.yanked_at ? 'yanked' : r.withdrawn_at ? 'withdrawn' : 'current'

const releaseHref = (r: Pick<Release, 'name'>) =>
  `/releases/${encodeURIComponent(r.name)}`

/** Every release, newest first, with a search held in the address. Making
 * one is the host's to offer (`onRelease` of the embed). */
export default function ReleasesPage() {
  const { data, isLoading, error } = useReleases()
  const list = useListParams('', ['state'])

  const wanted = list.q.trim().toLowerCase()
  const matching = (data ?? []).filter(
    (r) =>
      (!wanted ||
        r.name.toLowerCase().includes(wanted) ||
        r.title.toLowerCase().includes(wanted)) &&
      (!list.picks.state || stateOf(r) === list.picks.state),
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
          {r.yanked_at ? (
            <Badge variant="danger">Yanked</Badge>
          ) : (
            r.withdrawn_at && <Badge variant="attention">Withdrawn</Badge>
          )}
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
      info="A release freezes the records with a version, a citation and a content hash, and keeps the files they cite where they are, so a paper can say exactly which data it used and the data can be had back later, however the project has moved on."
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
                { value: 'current', label: 'Current' },
                { value: 'withdrawn', label: 'Withdrawn' },
                { value: 'yanked', label: 'Yanked' },
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
          emptyMessage="Make one when the data is ready to cite: it freezes the records as they are and keeps the files they cite."
        />
        <Pagination
          page={list.page}
          pageSize={list.size}
          total={matching.length}
          onPage={(page) => list.set({ page })}
          onPageSize={(size) => list.set({ size })}
        />
      </div>
    </Page>
  )
}
