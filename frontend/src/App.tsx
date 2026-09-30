import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import { RouteErrorBoundary } from './components/RouteErrorBoundary'
import { LoadingState } from './components/ui/States'

const CollectionsPage = lazy(() => import('./pages/CollectionsPage'))
const CollectionDetailPage = lazy(() => import('./pages/CollectionDetailPage'))
const ImportPage = lazy(() => import('./pages/ImportPage'))
const SchemasPage = lazy(() => import('./pages/SchemasPage'))
const SchemaDetailPage = lazy(() => import('./pages/SchemaDetailPage'))
const SchemaImportPage = lazy(() => import('./pages/SchemaImportPage'))
const SchemaRecordsPage = lazy(() => import('./pages/SchemaRecordsPage'))
const ViewRedirect = lazy(() => import('./pages/ViewRedirect'))
const RecordDetailPage = lazy(() => import('./pages/RecordDetailPage'))
const NewRecordPage = lazy(() => import('./pages/NewRecordPage'))
const RecentlyDeletedPage = lazy(() => import('./pages/RecentlyDeletedPage'))
const WorkflowsPage = lazy(() => import('./pages/WorkflowsPage'))
const WorkflowEditorPage = lazy(() => import('./pages/WorkflowEditorPage'))
const JobsPage = lazy(() => import('./pages/JobsPage'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))
const JobDetailPage = lazy(() => import('./pages/JobDetailPage'))
const TerminalPage = lazy(() => import('./pages/TerminalPage'))
const AiPage = lazy(() => import('./pages/AiPage'))
const PluginsPage = lazy(() => import('./pages/PluginsPage'))
const PluginEditorPage = lazy(() => import('./pages/PluginEditorPage'))
const ContainerPluginEditorPage = lazy(
  () => import('./pages/ContainerPluginEditorPage'),
)
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const LegalPage = lazy(() => import('./pages/LegalPage'))

export default function App() {
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
            <Route
              path="/views"
              element={<Navigate replace to="/collections" />}
            />
            <Route path="/schemas" element={<SchemasPage />} />
            <Route path="/schemas/:id" element={<SchemaDetailPage />} />
            <Route path="/schemas/:id/import" element={<SchemaImportPage />} />
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
            <Route path="/trash" element={<RecentlyDeletedPage />} />
            <Route path="/workflows" element={<WorkflowsPage />} />
            <Route
              path="/workflows/new"
              element={<WorkflowEditorPage isNew />}
            />
            <Route
              path="/workflows/:stem/edit"
              element={<WorkflowEditorPage />}
            />
            <Route path="/runs" element={<JobsPage />} />
            <Route path="/runs/:id" element={<JobDetailPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            {/* Legacy redirects */}
            <Route path="/jobs" element={<Navigate to="/runs" replace />} />
            <Route path="/jobs/:id" element={<Navigate to="/runs" replace />} />
            <Route path="/terminal" element={<TerminalPage />} />
            <Route path="/ai" element={<AiPage />} />
            <Route path="/plugins" element={<PluginsPage />} />
            <Route path="/plugins/new" element={<PluginEditorPage isNew />} />
            <Route path="/plugins/:stem/edit" element={<PluginEditorPage />} />
            <Route
              path="/plugins/container/:name/edit"
              element={<ContainerPluginEditorPage />}
            />
            <Route path="/settings" element={<SettingsPage />} />
            {/* Legacy redirect — Storage moved into Settings */}
            <Route
              path="/storage"
              element={<Navigate to="/settings" replace />}
            />
            <Route path="/legal" element={<LegalPage />} />
          </Routes>
        </Suspense>
      </RouteErrorBoundary>
    </Layout>
  )
}
