import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import { useDateFormat } from './hooks/useDateFormat'
import { RouteErrorBoundary } from './components/RouteErrorBoundary'
import { LoadingState } from './components/ui/States'
import { Gated, GatedFollowsRemote } from './components/FeatureGate'
import { SETTINGS_SECTION_FEATURES } from './utils/features'

const CollectionsPage = lazy(() => import('./pages/CollectionsPage'))
const CollectionDetailPage = lazy(() => import('./pages/CollectionDetailPage'))
const SchemasPage = lazy(() => import('./pages/SchemasPage'))
const SchemaDetailPage = lazy(() => import('./pages/SchemaDetailPage'))
const SchemaRecordsPage = lazy(() => import('./pages/SchemaRecordsPage'))
const ViewRedirect = lazy(() => import('./pages/ViewRedirect'))
const RecordDetailPage = lazy(() => import('./pages/RecordDetailPage'))
const ReleasesPage = lazy(() => import('./pages/ReleasesPage'))
const ReleasePage = lazy(() => import('./pages/ReleasePage'))
const NewRecordPage = lazy(() => import('./pages/NewRecordPage'))
const ImportPage = lazy(() => import('./pages/ImportPage'))
const ConnectPage = lazy(() => import('./pages/ConnectPage'))
const WorkflowsPage = lazy(() => import('./pages/WorkflowsPage'))
const WorkflowEditorPage = lazy(() => import('./pages/WorkflowEditorPage'))
const WorkflowPage = lazy(() => import('./pages/WorkflowPage'))
const JobsPage = lazy(() => import('./pages/JobsPage'))
const HealthPage = lazy(() => import('./pages/HealthPage'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))
/** The old Recently Deleted address: history showing what is deleted. */
const DELETED_VIEW = `/activity?activity.filter=${encodeURIComponent(
  JSON.stringify({
    and: [
      { field: 'now', op: 'eq', value: 'deleted' },
      { field: 'change', op: 'eq', value: 'delete' },
    ],
  }),
)}`
const ActivityPage = lazy(() => import('./pages/ActivityPage'))
const ExportsPage = lazy(() => import('./pages/ExportsPage'))
const ExportEditorPage = lazy(() => import('./pages/ExportEditorPage'))
const JobDetailPage = lazy(() => import('./pages/JobDetailPage'))
const TerminalPage = lazy(() => import('./pages/TerminalPage'))
const AiPage = lazy(() => import('./pages/AiPage'))
const PluginsPage = lazy(() => import('./pages/PluginsPage'))
const PluginEditorPage = lazy(() => import('./pages/PluginEditorPage'))
const ContainerPluginEditorPage = lazy(
  () => import('./pages/ContainerPluginEditorPage'),
)
const VolumePage = lazy(
  () => import('./components/settings/storage/VolumePage'),
)
const SettingsLayout = lazy(() => import('./pages/settings/SettingsLayout'))
const ThemeSection = lazy(() => import('./components/settings/ThemeSection'))
const DatabaseSection = lazy(
  () => import('./components/settings/DatabaseSection'),
)
const StorageSettings = lazy(
  () => import('./components/settings/storage/StorageSettings'),
)
const RetentionSection = lazy(
  () => import('./components/settings/RetentionSection'),
)
const SyncSection = lazy(() => import('./components/settings/SyncSection'))
const ExtensionSection = lazy(
  () => import('./components/host/ExtensionSection'),
)
const MembersSection = lazy(
  () => import('./components/settings/MembersSection'),
)
const UpdatesSection = lazy(
  () => import('./components/settings/UpdatesSection'),
)
const SyncReviewPage = lazy(() => import('./pages/SyncReviewPage'))
const MapSection = lazy(() => import('./components/settings/MapSection'))
const LogsSection = lazy(() => import('./components/settings/LogsSection'))
const AdvancedSection = lazy(
  () => import('./components/settings/AdvancedSection'),
)
const LegalPage = lazy(() => import('./pages/LegalPage'))

export default function App() {
  // Every date on screen is written in the chosen pattern; reading it here
  // re-renders the whole app when it changes (nothing below is memoised).
  useDateFormat()
  return (
    <Layout>
      <RouteErrorBoundary>
        <Suspense fallback={<LoadingState />}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/collections" element={<CollectionsPage />} />
            <Route path="/collections/:id" element={<CollectionDetailPage />} />
            <Route path="/collections/:id/new" element={<NewRecordPage />} />
            <Route path="/collections/:id/import" element={<ImportPage />} />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/connect" element={<ConnectPage />} />
            <Route
              path="/views"
              element={<Navigate replace to="/collections" />}
            />
            <Route path="/schemas" element={<SchemasPage />} />
            <Route path="/schemas/:id" element={<SchemaDetailPage />} />
            <Route path="/schemas/:id/views" element={<ViewRedirect />} />
            <Route
              path="/schemas/:id/records"
              element={<SchemaRecordsPage />}
            />
            <Route path="/schemas/:id/views/new" element={<ViewRedirect />} />
            <Route
              path="/schemas/:id/views/:viewName"
              element={<ViewRedirect />}
            />
            <Route path="/records/:id" element={<RecordDetailPage />} />
            <Route
              path="/trash"
              element={<Navigate to={DELETED_VIEW} replace />}
            />
            <Route
              path="/workflows"
              element={
                <Gated feature="local_workflows">
                  <WorkflowsPage />
                </Gated>
              }
            />
            <Route
              path="/workflows/new"
              element={
                <Gated feature="local_workflows">
                  <WorkflowEditorPage isNew />
                </Gated>
              }
            />
            <Route
              path="/workflows/:stem"
              element={
                <Gated feature="local_workflows">
                  <WorkflowPage />
                </Gated>
              }
            />
            <Route
              path="/workflows/:stem/edit"
              element={
                <Gated feature="local_workflows">
                  <WorkflowEditorPage />
                </Gated>
              }
            />
            <Route
              path="/runs"
              element={
                <Gated feature="local_workflows">
                  <JobsPage />
                </Gated>
              }
            />
            <Route
              path="/runs/:id"
              element={
                <Gated feature="local_workflows">
                  <JobDetailPage />
                </Gated>
              }
            />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/health" element={<HealthPage />} />
            <Route path="/activity" element={<ActivityPage />} />
            <Route path="/exports" element={<ExportsPage />} />
            <Route
              path="/releases"
              element={
                <Gated feature="releases">
                  <ReleasesPage />
                </Gated>
              }
            />
            <Route
              path="/releases/:name"
              element={
                <Gated feature="releases">
                  <ReleasePage />
                </Gated>
              }
            />
            <Route path="/exports/new" element={<ExportEditorPage />} />
            <Route
              path="/exports/:schema/:name"
              element={<ExportEditorPage />}
            />
            <Route
              path="/sync/review"
              element={
                <GatedFollowsRemote>
                  <SyncReviewPage />
                </GatedFollowsRemote>
              }
            />
            {/* Legacy redirects */}
            <Route path="/jobs" element={<Navigate to="/runs" replace />} />
            <Route path="/jobs/:id" element={<Navigate to="/runs" replace />} />
            <Route
              path="/terminal"
              element={
                <Gated feature="terminal">
                  <TerminalPage />
                </Gated>
              }
            />
            <Route
              path="/ai"
              element={
                <Gated feature="ai">
                  <AiPage />
                </Gated>
              }
            />
            <Route
              path="/plugins"
              element={
                <Gated feature="plugin_editor">
                  <PluginsPage />
                </Gated>
              }
            />
            <Route
              path="/plugins/new"
              element={
                <Gated feature="plugin_editor">
                  <PluginEditorPage isNew />
                </Gated>
              }
            />
            <Route
              path="/plugins/:stem/edit"
              element={
                <Gated feature="plugin_editor">
                  <PluginEditorPage />
                </Gated>
              }
            />
            <Route
              path="/plugins/container/:name/edit"
              element={
                <Gated feature="plugin_editor">
                  <ContainerPluginEditorPage />
                </Gated>
              }
            />
            <Route
              path="/settings/storage/volumes/:name"
              element={
                <Gated feature={['settings', 'volumes']}>
                  <VolumePage />
                </Gated>
              }
            />
            <Route
              path="/settings"
              element={
                <Gated feature="settings">
                  <SettingsLayout />
                </Gated>
              }
            >
              <Route
                path="appearance"
                element={
                  <Gated feature={SETTINGS_SECTION_FEATURES.appearance}>
                    <ThemeSection />
                  </Gated>
                }
              />
              <Route
                path="database"
                element={
                  <Gated feature={SETTINGS_SECTION_FEATURES.database}>
                    <DatabaseSection />
                  </Gated>
                }
              />
              <Route
                path="storage"
                element={
                  <Gated feature={SETTINGS_SECTION_FEATURES.storage}>
                    <StorageSettings />
                  </Gated>
                }
              />
              <Route
                path="retention"
                element={
                  <Gated feature={SETTINGS_SECTION_FEATURES.retention}>
                    <RetentionSection />
                  </Gated>
                }
              />
              <Route
                path="recently-deleted"
                element={<Navigate to="/settings/retention" replace />}
              />
              <Route
                path="members"
                element={
                  <Gated feature={SETTINGS_SECTION_FEATURES.members}>
                    <MembersSection />
                  </Gated>
                }
              />
              <Route path="sync" element={<SyncSection />} />
              <Route path="x/:id" element={<ExtensionSection />} />
              <Route
                path="map"
                element={
                  <Gated feature={SETTINGS_SECTION_FEATURES.map}>
                    <MapSection />
                  </Gated>
                }
              />
              <Route
                path="updates"
                element={
                  <Gated feature={SETTINGS_SECTION_FEATURES.updates}>
                    <UpdatesSection />
                  </Gated>
                }
              />
              <Route
                path="logs"
                element={
                  <Gated feature={SETTINGS_SECTION_FEATURES.logs}>
                    <LogsSection />
                  </Gated>
                }
              />
              <Route
                path="advanced"
                element={
                  <Gated feature={SETTINGS_SECTION_FEATURES.advanced}>
                    <AdvancedSection />
                  </Gated>
                }
              />
            </Route>
            {/* Legacy redirect — Storage lives under Settings */}
            <Route
              path="/storage"
              element={<Navigate to="/settings/storage" replace />}
            />
            <Route path="/legal" element={<LegalPage />} />
          </Routes>
        </Suspense>
      </RouteErrorBoundary>
    </Layout>
  )
}
