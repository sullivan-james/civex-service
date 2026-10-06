import { ExportsList } from '../components/files/ExportsList'
import { SavedExports } from '../components/exports/SavedExports'
import { Page, TabNav, TabPanel, useTabParam } from '../components/ui'
import { useSchemas } from '../hooks/useSchemas'

const TABS = [
  { id: 'saved' as const, label: 'Saved' },
  { id: 'made' as const, label: 'Made' },
]

/** Everything about exports in one place: the ones that are set up (which files
 * and tables to take, and how to lay out the folder), run on a collection, and the
 * folders they have made. The list is held in the address like every other, so a
 * link from a record or a schema lands on the right view. */
export default function ExportsPage() {
  const [tab, setTab] = useTabParam(TABS, 'saved')
  const { data: schemas = [] } = useSchemas()

  return (
    <Page
      title="Exports"
      info="Set up which files and tables to take and how to lay out the folder, then run one on a collection. An export starts from a kind of record: it takes that kind and everything inside it."
      tabs={
        <TabNav label="Exports" value={tab} onChange={setTab} tabs={TABS} />
      }
    >
      <TabPanel id="saved" value={tab}>
        <SavedExports schemas={schemas} />
      </TabPanel>
      <TabPanel id="made" value={tab}>
        <ExportsList />
      </TabPanel>
    </Page>
  )
}
