import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Create from "./pages/Create";
import Videos from "./pages/Videos";
import VideoDetail from "./pages/VideoDetail";
import VideoEditor from "./pages/VideoEditor";
import Providers from "./pages/Providers";
import Settings from "./pages/Settings";
import Channels from "./pages/Channels";
import ChannelDetail from "./pages/ChannelDetail";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="create" element={<Create />} />
        <Route path="canais" element={<Channels />} />
        <Route path="canais/:id" element={<ChannelDetail />} />
        {/* Projects was merged into Canais — keep old links working. */}
        <Route path="projects" element={<Navigate to="/canais" replace />} />
        <Route path="videos" element={<Videos />} />
        <Route path="videos/:id" element={<VideoDetail />} />
        <Route path="videos/:id/editor" element={<VideoEditor />} />
        <Route path="providers" element={<Providers />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
