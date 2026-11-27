import { Navigate, Route, Routes } from "react-router-dom";
import { Loading } from "./components/ui";
import { useAuth } from "./context/AuthContext";
import AppLayout from "./layouts/AppLayout";
import Appointments from "./pages/Appointments";
import ChatHome from "./pages/ChatHome";
import Consultations from "./pages/Consultations";
import Dashboard from "./pages/Dashboard";
import DocumentDetail from "./pages/DocumentDetail";
import Family from "./pages/Family";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Medications from "./pages/Medications";
import NotFound from "./pages/NotFound";
import Records from "./pages/Records";
import Register from "./pages/Register";
import SettingsPage from "./pages/Settings";
import Timeline from "./pages/Timeline";
import Upload from "./pages/Upload";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading label="Opening your records…" />;
  return user ? children : <Navigate to="/login" replace />;
}

function GuestOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  return user ? <Navigate to="/app" replace /> : children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<GuestOnly><Login /></GuestOnly>} />
      <Route path="/register" element={<GuestOnly><Register /></GuestOnly>} />
      <Route path="/app" element={<Protected><AppLayout /></Protected>}>
        <Route index element={<ChatHome />} />
        <Route path="overview" element={<Dashboard />} />
        <Route path="records" element={<Records />} />
        <Route path="records/upload" element={<Upload />} />
        <Route path="records/:id" element={<DocumentDetail />} />
        <Route path="timeline" element={<Timeline />} />
        <Route path="consultations" element={<Consultations />} />
        <Route path="assistant" element={<Navigate to="/app" replace />} />
        <Route path="voice" element={<Navigate to="/app" replace />} />
        <Route path="medications" element={<Medications />} />
        <Route path="appointments" element={<Appointments />} />
        <Route path="family" element={<Family />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
