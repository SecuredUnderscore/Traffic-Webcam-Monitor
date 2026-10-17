import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bell, FlaskConical, LayoutGrid, Settings as SettingsIcon } from "lucide-react";
import { api } from "./api";
import Dashboard from "./pages/Dashboard";
import CameraPage from "./pages/CameraPage";
import EventsPage from "./pages/EventsPage";
import LabPage from "./pages/LabPage";
import SettingsPage from "./pages/SettingsPage";
import { StatusDot } from "./components/ui";
import { cx } from "./util";

function Logo() {
  return (
    <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="#101828" />
      <rect x="11" y="4" width="10" height="24" rx="4" fill="#1b2840" stroke="#38bdf8" strokeWidth="1.5" />
      <circle cx="16" cy="10" r="2.6" fill="#ef4444" />
      <circle cx="16" cy="16" r="2.6" fill="#eab308" />
      <circle cx="16" cy="22" r="2.6" fill="#22c55e" />
    </svg>
  );
}

export default function App() {
  const loc = useLocation();
  const cams = useQuery({ queryKey: ["cameras"], queryFn: api.cameras, refetchInterval: 10000 });
  const unread = useQuery({ queryKey: ["unread"], queryFn: api.unread, refetchInterval: 15000 });
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <Logo />
          <div>
            <div className="brand-name">TrafficWatch</div>
            <div className="brand-sub">traffic-cam change alerts</div>
          </div>
        </div>
        <NavLink to="/" end className={({ isActive }) => cx("nav-link", isActive && "active")}><LayoutGrid size={17} /> Cameras</NavLink>
        <NavLink to="/events" className={({ isActive }) => cx("nav-link", isActive && "active")}>
          <Bell size={17} /> Alerts {!!unread.data?.count && <span className="nav-badge">{unread.data.count}</span>}
        </NavLink>
        <NavLink to="/lab" className={({ isActive }) => cx("nav-link", isActive && "active")}><FlaskConical size={17} /> Detector Lab</NavLink>
        <NavLink to="/settings" className={({ isActive }) => cx("nav-link", isActive && "active")}><SettingsIcon size={17} /> Settings</NavLink>

        {!!cams.data?.length && <div className="sidebar-section">Cameras</div>}
        <div style={{ overflow: "auto" }}>
          {cams.data?.map((c) => (
            <NavLink key={c.id} to={`/cameras/${c.id}`} className={cx("sidebar-cam", loc.pathname === `/cameras/${c.id}` && "active")}>
              <StatusDot status={c.status} />
              <span className="ellipsis">{c.name}</span>
            </NavLink>
          ))}
        </div>
        <div className="sidebar-foot">v{meta.data?.version ?? "…"} · runs locally, no cloud AI</div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/cameras/:id" element={<CameraPage />} />
          <Route path="/events" element={<EventsPage />} />
          <Route path="/lab" element={<LabPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
