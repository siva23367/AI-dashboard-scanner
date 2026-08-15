import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";
import Sidebar from "./components/Sidebar";
import MobileNav from "./components/MobileNav";
import { ScanSweep } from "./components/ui";
import Login from "./pages/Login";
import Home from "./pages/Home";
import WebsiteScan from "./pages/WebsiteScan";
import PdfIngest from "./pages/PdfIngest";
import ProductResearch from "./pages/ProductResearch";
import AskDashboards from "./pages/AskDashboards";
import Reports from "./pages/Reports";

function FullScreenLoading() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-navy-900">
      <div className="w-64">
        <ScanSweep />
        <p className="text-white/50 text-[13px] text-center mt-3">Loading Sriya Web Intelligence…</p>
      </div>
    </div>
  );
}

function Protected({ children }) {
  const { status } = useAuth();
  if (status === "checking") return <FullScreenLoading />;
  if (status === "out") return <Navigate to="/login" replace />;
  return children;
}

function Layout({ children }) {
  return (
    <div className="min-h-screen flex bg-bg">
      <Sidebar />
      <div className="flex-1 min-w-0">
        <MobileNav />
        <main className="max-w-6xl mx-auto px-5 md:px-8 py-7">{children}</main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/*"
        element={
          <Protected>
            <Layout>
              <Routes>
                <Route path="/" element={<Home />} />
                <Route path="/website" element={<WebsiteScan />} />
                <Route path="/pdf" element={<PdfIngest />} />
                <Route path="/research" element={<ProductResearch />} />
                <Route path="/ask" element={<AskDashboards />} />
                <Route path="/reports" element={<Reports />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Layout>
          </Protected>
        }
      />
    </Routes>
  );
}
