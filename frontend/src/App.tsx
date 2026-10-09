import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Create from "./pages/Create";
import Projects from "./pages/Projects";
import Videos from "./pages/Videos";
import VideoDetail from "./pages/VideoDetail";
import Providers from "./pages/Providers";
import Agents from "./pages/Agents";
import Prompts from "./pages/Prompts";
import Accounts from "./pages/Accounts";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="create" element={<Create />} />
        <Route path="projects" element={<Projects />} />
        <Route path="videos" element={<Videos />} />
        <Route path="videos/:id" element={<VideoDetail />} />
        <Route path="providers" element={<Providers />} />
        <Route path="agents" element={<Agents />} />
        <Route path="prompts" element={<Prompts />} />
        <Route path="accounts" element={<Accounts />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
