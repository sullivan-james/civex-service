import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import CollectionsPage from './pages/CollectionsPage'
import CollectionDetailPage from './pages/CollectionDetailPage'
import SchemasPage from './pages/SchemasPage'
import SchemaDetailPage from './pages/SchemaDetailPage'
import RecordDetailPage from './pages/RecordDetailPage'
import WorkflowsPage from './pages/WorkflowsPage'
import JobsPage from './pages/JobsPage'
import JobDetailPage from './pages/JobDetailPage'
import TerminalPage from './pages/TerminalPage'
import StorePage from './pages/StorePage'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/collections" replace />} />
        <Route path="/collections" element={<CollectionsPage />} />
        <Route path="/collections/:id" element={<CollectionDetailPage />} />
        {/* Legacy redirects */}
        <Route path="/datasets" element={<Navigate to="/collections" replace />} />
        <Route path="/datasets/:id" element={<Navigate to="/collections" replace />} />
        <Route path="/schemas" element={<SchemasPage />} />
        <Route path="/schemas/:id" element={<SchemaDetailPage />} />
        <Route path="/records/:id" element={<RecordDetailPage />} />
        <Route path="/workflows" element={<WorkflowsPage />} />
        <Route path="/runs" element={<JobsPage />} />
        <Route path="/runs/:id" element={<JobDetailPage />} />
        {/* Legacy redirects */}
        <Route path="/jobs" element={<Navigate to="/runs" replace />} />
        <Route path="/jobs/:id" element={<Navigate to="/runs" replace />} />
        <Route path="/terminal" element={<TerminalPage />} />
        <Route path="/storage" element={<StorePage />} />
      </Routes>
    </Layout>
  )
}
