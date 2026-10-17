import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bell, FlaskConical, LayoutGrid, Monitor, Moon, Settings as SettingsIcon, Sun, TrafficCone } from "lucide-react";
import { api } from "./api";
import Dashboard from "./pages/Dashboard";
import CameraPage from "./pages/CameraPage";
import EventsPage from "./pages/EventsPage";
import LabPage from "./pages/LabPage";
import SettingsPage from "./pages/SettingsPage";
import { StatusIcon } from "./components/ui";
import { applyTheme, cx, getTheme, type Theme } from "./util";

const THEMES: { id: Theme; label: string; Icon: typeof Sun }[] = [
  { id: "system", label: "System theme", Icon: Monitor },
  { id: "light", label: "Light theme", Icon: Sun },
  { id: "dark", label: "Dark theme", Icon: Moon },
];

function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(getTheme);
  return (
    <div className="seg" role="group" aria-label="Theme">
      {THEMES.map(({ id, label, Icon }) => (
        <button
          key={id}
          className={cx(theme === id && "on")}
          title={label}
          aria-label={label}
          aria-pressed={theme === id}
          style={{ height: 26, padding: "0 8px" }}
          onClick={() => {
            applyTheme(id);
            setTheme(id);
          }}
        >
          <Icon size={14} />
        </button>
      ))}
    </div>
  );
}

const NAV = [
  { to: "/", label: "Cameras", Icon: LayoutGrid, end: true },
  { to: "/events", label: "Alerts", Icon: Bell },
  { to: "/lab", label: "Detector Lab", Icon: FlaskConical },
  { to: "/settings", label: "Settings", Icon: SettingsIcon },
];

export default function App() {
  const cams = useQuery({ queryKey: ["cameras"], queryFn: api.cameras, refetchInterval: 10000 });
  const unread = useQuery({ queryKey: ["unread"], queryFn: api.unread, refetchInterval: 15000 });
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const unreadCount = unread.data?.count ?? 0;

  const links = NAV.map(({ to, label, Icon, end }) => (
    <NavLink key={to} to={to} end={end} className={({ isActive }) => cx("nav-link", isActive && "active")}>
      <Icon size={16} /> {label}
      {to === "/events" && unreadCount > 0 && <span className="nav-count" title={`${unreadCount} unseen alerts`}>{unreadCount}</span>}
    </NavLink>
  ));

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <TrafficCone size={18} /> TrafficWatch
        </div>
        {links}
        {!!cams.data?.length && <div className="sidebar-heading">Cameras</div>}
        <div className="sidebar-cams">
          {cams.data?.map((c) => (
            <NavLink key={c.id} to={`/cameras/${c.id}`} className={({ isActive }) => cx("sidebar-cam", isActive && "active")}>
              <StatusIcon status={c.status} />
              <span className="ellipsis">{c.name}</span>
            </NavLink>
          ))}
        </div>
        <div className="sidebar-foot">
          <span className="grow">v{meta.data?.version ?? "…"}</span>
          <ThemeSwitch />
        </div>
      </aside>
      <main className="main">
        <nav className="topnav">{links}</nav>
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
