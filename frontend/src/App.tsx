import { Routes, Route, Navigate } from 'react-router'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import CollectionsPage from './pages/CollectionsPage'
import CollectionDetailPage from './pages/CollectionDetailPage'
import ImportPage from './pages/ImportPage'
import SchemasPage from './pages/SchemasPage'
import SchemaDetailPage from './pages/SchemaDetailPage'
import ViewsIndexPage from './pages/ViewsIndexPage'
import ViewsPage from './pages/ViewsPage'
import ViewBuilderPage from './pages/ViewBuilderPage'
import RecordDetailPage from './pages/RecordDetailPage'
import RecentlyDeletedPage from './pages/RecentlyDeletedPage'
import WorkflowsPage from './pages/WorkflowsPage'
import JobsPage from './pages/JobsPage'
import AnalyticsPage from './pages/AnalyticsPage'
import JobDetailPage from './pages/JobDetailPage'
import TerminalPage from './pages/TerminalPage'
import AiPage from './pages/AiPage'
import PluginsPage from './pages/PluginsPage'
import SettingsPage from './pages/SettingsPage'
import LegalPage from './pages/LegalPage'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/collections" element={<CollectionsPage />} />
        <Route path="/collections/:id" element={<CollectionDetailPage />} />
        <Route path="/collections/:id/import" element={<ImportPage />} />
        <Route path="/views" element={<ViewsIndexPage />} />
        <Route path="/schemas" element={<SchemasPage />} />
        <Route path="/schemas/:id" element={<SchemaDetailPage />} />
        <Route path="/schemas/:id/views" element={<ViewsPage />} />
        <Route path="/schemas/:id/views/new" element={<ViewBuilderPage />} />
        <Route
          path="/schemas/:id/views/:viewName"
          element={<ViewBuilderPage />}
        />
        <Route path="/records/:id" element={<RecordDetailPage />} />
        <Route path="/trash" element={<RecentlyDeletedPage />} />
        <Route path="/workflows" element={<WorkflowsPage />} />
        <Route path="/runs" element={<JobsPage />} />
        <Route path="/runs/:id" element={<JobDetailPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        {/* Legacy redirects */}
        <Route path="/jobs" element={<Navigate to="/runs" replace />} />
        <Route path="/jobs/:id" element={<Navigate to="/runs" replace />} />
        <Route path="/terminal" element={<TerminalPage />} />
        <Route path="/ai" element={<AiPage />} />
        <Route path="/plugins" element={<PluginsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        {/* Legacy redirect — Storage moved into Settings */}
        <Route path="/storage" element={<Navigate to="/settings" replace />} />
        <Route path="/legal" element={<LegalPage />} />
      </Routes>
    </Layout>
  )
}
