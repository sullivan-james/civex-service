import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import DatasetsPage from './pages/DatasetsPage'
import DatasetDetailPage from './pages/DatasetDetailPage'
import SchemasPage from './pages/SchemasPage'
import SchemaDetailPage from './pages/SchemaDetailPage'
import RecordDetailPage from './pages/RecordDetailPage'
import WorkflowsPage from './pages/WorkflowsPage'
import JobsPage from './pages/JobsPage'
import JobDetailPage from './pages/JobDetailPage'
import TerminalPage from './pages/TerminalPage'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/datasets" replace />} />
        <Route path="/datasets" element={<DatasetsPage />} />
        <Route path="/datasets/:id" element={<DatasetDetailPage />} />
        <Route path="/schemas" element={<SchemasPage />} />
        <Route path="/schemas/:id" element={<SchemaDetailPage />} />
        <Route path="/records/:id" element={<RecordDetailPage />} />
        <Route path="/workflows" element={<WorkflowsPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/jobs/:id" element={<JobDetailPage />} />
        <Route path="/terminal" element={<TerminalPage />} />
      </Routes>
    </Layout>
  )
}
