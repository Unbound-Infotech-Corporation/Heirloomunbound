import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BookOpen,
  Camera,
  Cpu,
  Database,
  Feather,
  Home,
  Image as ImageIcon,
  ListTodo,
  LogOut,
  Mail,
  Menu,
  MessageCircleHeart,
  MonitorSpeaker,
  Settings as SettingsIcon,
  SlidersHorizontal,
  Sparkles,
  Sunrise,
  ToggleRight,
  Upload,
  User as UserIcon,
  Users,
  Volume2,
  Wrench,
  X,
} from "lucide-react";
import QuickCapture from "./QuickCapture";
import SiteFooter from "./SiteFooter";
import StudioWindow, { StudioMenuBar } from "./StudioWindow";
import { getAppMenubarItems, getWindowMenus } from "./studio";
import TourOverlay from "./TourOverlay";
import { useAuth } from "../lib/auth";

const navItems = [
  { to: "/today", label: "Today", icon: Sunrise, tid: "nav-today" },
  { to: "/dashboard", label: "Archive", icon: Home, tid: "nav-dashboard" },
  { to: "/reminders", label: "Reminders", icon: ListTodo, tid: "nav-reminders" },
  { to: "/interviewer", label: "Interviewer", icon: MessageCircleHeart, tid: "nav-interviewer" },
  { to: "/journal", label: "Voice journal", icon: Feather, tid: "nav-journal" },
  { to: "/library", label: "Library", icon: BookOpen, tid: "nav-library" },
  { to: "/photos", label: "Photos", icon: ImageIcon, tid: "nav-photos" },
  { to: "/photo-story", label: "Photo → Story", icon: Camera, tid: "nav-photo-story" },
  { to: "/sources", label: "Sources", icon: Database, tid: "nav-sources" },
  { to: "/import", label: "Import", icon: Upload, tid: "nav-import" },
  { to: "/twin", label: "Talk to twin", icon: Sparkles, tid: "nav-twin" },
  { to: "/mixer", label: "Mixer", icon: Volume2, tid: "nav-mixer" },
  { to: "/models", label: "Models", icon: Cpu, tid: "nav-models" },
  { to: "/abilities", label: "Abilities", icon: ToggleRight, tid: "nav-abilities" },
  { to: "/personality", label: "Your portrait", icon: UserIcon, tid: "nav-personality" },
  { to: "/skills", label: "Skills", icon: Wrench, tid: "nav-skills" },
  { to: "/companion", label: "Local PC", icon: MonitorSpeaker, tid: "nav-companion" },
  { to: "/heirs", label: "Heirs", icon: Users, tid: "nav-heirs" },
  { to: "/letters", label: "Sealed letters", icon: Mail, tid: "nav-letters" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, tid: "nav-settings" },
];

const WINDOW_TITLES = {
  "/today": "Today",
  "/dashboard": "Archive",
  "/reminders": "Reminders",
  "/interviewer": "Interviewer",
  "/journal": "Voice Journal",
  "/library": "Library",
  "/photos": "Photos",
  "/photo-story": "Photo → Story",
  "/sources": "Sources",
  "/import": "Import",
  "/twin": "Twin",
  "/mixer": "Mixer",
  "/models": "Models",
  "/abilities": "Abilities",
  "/personality": "Portrait",
  "/skills": "Skills",
  "/companion": "Local PC",
  "/heirs": "Heirs",
  "/letters": "Sealed Letters",
  "/settings": "Settings",
  "/avatar-studio": "Avatar Studio",
  "/setup/keys": "API Keys",
};

function SidebarContent({ user, logout, onNavigate, navigateRoot }) {
  return (
    <>
      <button
        onClick={navigateRoot}
        data-testid="sidebar-brand"
        className="text-left px-7 pt-8 pb-6 border-b"
        style={{ borderColor: "var(--border-default)" }}
      >
        <div className="overline mb-2">est. {new Date().getFullYear()}</div>
        <div className="font-serif text-3xl tracking-tight" style={{ color: "var(--text-primary)" }}>
          Heirloom
        </div>
        <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
          a continuation of you
        </div>
      </button>

      <nav className="flex-1 px-3 py-5 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              data-testid={item.tid}
              onClick={onNavigate}
              className={({ isActive }) =>
                `group flex items-center gap-3 px-4 py-2.5 rounded-sm transition-colors duration-200 ${
                  isActive ? "text-[var(--accent)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                }`
              }
              style={({ isActive }) =>
                isActive
                  ? { background: "var(--accent-muted)", borderLeft: "2px solid var(--accent)" }
                  : { borderLeft: "2px solid transparent" }
              }
            >
              <Icon className="h-4 w-4" />
              <span className="text-sm tracking-wide">{item.label}</span>
            </NavLink>
          );
        })}
      </nav>

      <div className="px-5 py-5 border-t" style={{ borderColor: "var(--border-default)" }}>
        <div className="flex items-center gap-3 mb-3">
          {user?.picture ? (
            <img
              src={user.picture}
              alt=""
              className="h-9 w-9 rounded-full object-cover"
              style={{ border: "1px solid var(--border-default)" }}
            />
          ) : (
            <div
              className="h-9 w-9 rounded-full flex items-center justify-center font-serif text-lg"
              style={{ background: "var(--bg-elevated)", color: "var(--accent)" }}
            >
              {(user?.name || user?.email || "?")[0]?.toUpperCase()}
            </div>
          )}
          <div className="overflow-hidden">
            <div data-testid="sidebar-user-name" className="text-sm truncate" style={{ color: "var(--text-primary)" }}>
              {user?.name || "—"}
            </div>
            <div className="text-xs truncate" style={{ color: "var(--text-muted)" }}>
              {user?.email}
            </div>
          </div>
        </div>
        <button
          onClick={logout}
          data-testid="logout-button"
          className="w-full flex items-center gap-2 justify-center text-xs py-2 rounded-sm transition-colors"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
        >
          <LogOut className="h-3.5 w-3.5" /> Sign out
        </button>
      </div>
    </>
  );
}

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [captureOpen, setCaptureOpen] = useState(false);

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e) => e.key === "Escape" && setDrawerOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const sidebarProps = {
    user,
    logout,
    onNavigate: () => setDrawerOpen(false),
    navigateRoot: () => {
      setDrawerOpen(false);
      navigate("/dashboard");
    },
  };

  const title = WINDOW_TITLES[location.pathname] || "Heirloom";
  const menuCtx = useMemo(
    () => ({ navigate, logout, setCaptureOpen }),
    [navigate, logout]
  );
  const menus = useMemo(
    () => getWindowMenus(location.pathname, menuCtx),
    [location.pathname, menuCtx]
  );
  const appMenus = useMemo(() => getAppMenubarItems(menuCtx), [menuCtx]);

  return (
    <div className="studio-shell" style={{ background: "#1e1e1e" }}>
      <header className="studio-app-menubar" data-testid="studio-app-menubar">
        <button type="button" className="studio-brand" onClick={() => navigate("/dashboard")} data-testid="studio-brand">
          Heirloom
        </button>
        <StudioMenuBar menus={appMenus} inline />
        <div className="ml-auto text-[11px] tracking-wide px-3" style={{ color: "#9a9a9a" }}>
          {user?.name || user?.email || "signed in"}
        </div>
      </header>

      <div className="studio-body">
        <aside data-testid="app-sidebar" className="studio-dock hidden lg:flex">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                data-testid={item.tid}
                title={item.label}
                className={({ isActive }) => `studio-dock-btn ${isActive ? "is-active" : ""}`}
              >
                <Icon className="h-4 w-4" />
                <span className="sr-only">{item.label}</span>
              </NavLink>
            );
          })}
        </aside>

        {drawerOpen && (
          <button
            type="button"
            aria-label="Close menu"
            onClick={() => setDrawerOpen(false)}
            data-testid="mobile-drawer-scrim"
            className="lg:hidden fixed inset-0 z-40"
            style={{ background: "rgba(8,7,6,0.66)", backdropFilter: "blur(6px)" }}
          />
        )}
        <aside
          data-testid="mobile-drawer"
          className={`lg:hidden fixed top-0 left-0 bottom-0 z-50 w-72 max-w-[85vw] border-r flex flex-col transition-transform duration-250 ${
            drawerOpen ? "translate-x-0" : "-translate-x-full"
          }`}
          style={{ borderColor: "var(--border-default)", background: "var(--bg-surface)" }}
        >
          <SidebarContent {...sidebarProps} />
        </aside>

        <div className="studio-canvas">
          <div className="lg:hidden sticky top-0 z-30 flex items-center gap-3 px-4 py-3 border-b" style={{ background: "#2b2b2b", borderColor: "#111" }}>
            <button
              onClick={() => setDrawerOpen(true)}
              data-testid="mobile-menu-open"
              aria-label="Open menu"
              className="p-2 -ml-2 rounded-sm"
              style={{ color: "var(--text-primary)" }}
            >
              <Menu className="h-5 w-5" />
            </button>
            <button onClick={() => navigate("/dashboard")} className="font-serif text-lg" data-testid="mobile-brand">
              Heirloom
            </button>
          </div>

          <StudioWindow title={title} menus={menus} testId="studio-document">
            {captureOpen && (
              <div className="px-4 pt-4">
                <QuickCapture />
              </div>
            )}
            <Outlet />
            <SiteFooter />
          </StudioWindow>
        </div>
      </div>

      <footer className="studio-statusbar" data-testid="studio-statusbar">
        <span>Heirloom Studio</span>
        <span className="mx-2">·</span>
        <button type="button" onClick={() => navigate("/mixer")}>
          Mixer
        </button>
        <span className="mx-2">·</span>
        <button type="button" onClick={() => navigate("/models")}>
          Models
        </button>
        <SlidersHorizontal className="h-3 w-3 ml-auto mr-2 opacity-50" />
        <span>{title}</span>
      </footer>

      {drawerOpen && (
        <button
          onClick={() => setDrawerOpen(false)}
          data-testid="mobile-drawer-close"
          className="lg:hidden fixed top-3 right-3 z-[60] p-2 rounded-sm"
          style={{ background: "var(--bg-surface)", color: "var(--text-primary)", border: "1px solid var(--border-default)" }}
          aria-label="Close menu"
        >
          <X className="h-4 w-4" />
        </button>
      )}

      <TourOverlay />
    </div>
  );
}
