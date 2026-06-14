import { BrowserRouter, Route, Routes, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import RepoPage, { RepoOverview } from "./pages/RepoPage";
import LoginPage from "./pages/LoginPage";
import NewRepoPage from "./pages/NewRepoPage";
import SchemasPage from "./pages/SchemasPage";
import DatasetListPage from "./pages/DatasetListPage";
import RecordListPage from "./pages/RecordListPage";
import RecordDetailPage from "./pages/RecordDetailPage";
import CommitHistoryPage from "./pages/CommitHistoryPage";
import UserSettingsPage from "./pages/UserSettingsPage";
import { useParams } from "react-router-dom";

function OverviewIndex() {
  const { owner, name } = useParams<{ owner: string; name: string }>();
  return <RepoOverview owner={owner!} name={name!} />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/repos/new" element={<NewRepoPage />} />

          {/* Repo with tabbed layout */}
          <Route path="/:owner/:name" element={<RepoPage />}>
            <Route index element={<OverviewIndex />} />
            <Route path="schemas" element={<SchemasPage />} />
            <Route path="datasets" element={<DatasetListPage />} />
            <Route path="commits" element={<CommitHistoryPage />} />
          </Route>

          {/* Data sub-pages (use their own breadcrumbs) */}
          <Route path="/:owner/:name/datasets/:dataset" element={<RecordListPage />} />
          <Route path="/:owner/:name/records/:recordId" element={<RecordDetailPage />} />

          <Route path="/settings" element={<UserSettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
