import { motion } from "framer-motion";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  BookOpen,
  Compass,
  Feather,
  Headphones,
  Home,
  LogOut,
  MessageCircleHeart,
  Settings as SettingsIcon,
  Sparkles,
  Upload,
  Users,
  Wrench,
} from "lucide-react";
import { useAuth } from "../lib/auth";

const navItems = [
  { to: "/dashboard", label: "Archive", icon: Home, tid: "nav-dashboard" },
  { to: "/interviewer", label: "Interviewer", icon: MessageCircleHeart, tid: "nav-interviewer" },
  { to: "/journal", label: "Voice journal", icon: Feather, tid: "nav-journal" },
  { to: "/library", label: "Library", icon: BookOpen, tid: "nav-library" },
  { to: "/import", label: "Import", icon: Upload, tid: "nav-import" },
  { to: "/twin", label: "Talk to twin", icon: Sparkles, tid: "nav-twin" },
  { to: "/skills", label: "Skills", icon: Wrench, tid: "nav-skills" },
  { to: "/heirs", label: "Heirs", icon: Users, tid: "nav-heirs" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, tid: "nav-settings" },
];

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex" style={{ background: "var(--bg-base)" }}>
      <aside
        data-testid="app-sidebar"
        className="w-64 shrink-0 border-r flex flex-col"
        style={{ borderColor: "var(--border-default)", background: "var(--bg-surface)" }}
      >
        <button
          onClick={() => navigate("/dashboard")}
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

        <nav className="flex-1 px-3 py-5 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                data-testid={item.tid}
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
            className="w-full flex items-center justify-center gap-2 text-xs py-2 rounded-sm transition-colors"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
          >
            <LogOut className="h-3.5 w-3.5" /> Sign out
          </button>
        </div>
      </aside>

      <motion.main
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: "easeOut" }}
        className="flex-1 overflow-y-auto"
      >
        <Outlet />
      </motion.main>
    </div>
  );
}
