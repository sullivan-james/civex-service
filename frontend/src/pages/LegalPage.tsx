import { useLicense, usePolicies } from '../hooks/useLegal'
import {
  ErrorState,
  Page,
  Skeleton,
  TabNav,
  TabPanel,
  useTabParam,
} from '../components/ui'
import { errorMessage } from '../lib/errors'

function Document({ text }: { text: string }) {
  return (
    <pre className="whitespace-pre-wrap rounded-lg border border-border bg-canvas p-4 font-mono text-sm text-fg">
      {text}
    </pre>
  )
}

/** The software license, then one tab per policy document this deployment
 * has. */
export default function LegalPage() {
  const license = useLicense()
  const policies = usePolicies()
  const docs = [
    { id: 'license', label: 'License' },
    ...(policies.data ?? []).map((p) => ({ id: p.stem, label: p.title })),
  ]
  const [tab, setTab] = useTabParam(docs, 'license')

  return (
    <Page title="Licenses & Policies">
      {policies.isLoading || license.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <>
          <TabNav label="Documents" tabs={docs} value={tab} onChange={setTab} />
          <TabPanel id="license" value={tab}>
            {license.error || !license.data ? (
              <ErrorState
                message={
                  license.error
                    ? errorMessage(license.error)
                    : 'Failed to load license'
                }
              />
            ) : (
              <Document text={license.data.text} />
            )}
          </TabPanel>
          {(policies.data ?? []).map((p) => (
            <TabPanel key={p.stem} id={p.stem} value={tab}>
              <Document text={p.content} />
            </TabPanel>
          ))}
        </>
      )}
    </Page>
  )
}
