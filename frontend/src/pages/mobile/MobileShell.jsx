import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Camera, History, Home, Phone, Puzzle, Sparkles } from "lucide-react";
import { api } from "@/lib/api";

/**
 * Mobile PWA shell — bottom tab bar + safe-area padding for iOS.
 * Routes:
 *   /m           → default → redirect to /m/call
 *   /m/call      → in-app dialer + PSTN (the phone-native add-on)
 *   /m/twin      → talk to the twin against the home archive
 *   /m/capture   → voice memo + photo capture
 *   /m/history   → recent calls + memories
 *   /m/packs     → optional integrations (only those on at the desktop)
 */
const TABS = [
  { to: "/m/call", label: "Call", icon: Phone, tid: "mobile-tab-call" },
  { to: "/m/twin", label: "Twin", icon: Sparkles, tid: "mobile-tab-twin" },
  { to: "/m/capture", label: "Capture", icon: Camera, tid: "mobile-tab-capture" },
  { to: "/m/history", label: "Recent", icon: History, tid: "mobile-tab-history" },
  { to: "/m/packs", label: "Packs", icon: Puzzle, tid: "mobile-tab-packs" },
];

export default function MobileShell() {
  const loc = useLocation();
  const [installable, setInstallable] = useState(null);
  const [home, setHome] = useState(null);

  useEffect(() => {
    const onPrompt = (e) => {
      e.preventDefault();
      setInstallable(e);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  useEffect(() => {
    api.get("/mobile/home").then(({ data }) => setHome(data)).catch(() => {});
  }, [loc.pathname]);

  const promptInstall = async () => {
    if (!installable) return;
    installable.prompt();
    await installable.userChoice;
    setInstallable(null);
  };

  const online = Boolean(home?.home?.online);

  return (
    <div
      className="min-h-screen flex flex-col"
      style={{
        background: "var(--bg-base)",
        color: "var(--text-primary)",
        paddingTop: "env(safe-area-inset-top)",
        paddingBottom: "calc(64px + env(safe-area-inset-bottom))",
      }}
      data-testid="mobile-shell"
    >
      {installable && (
        <button
          onClick={promptInstall}
          data-testid="mobile-install-btn"
          className="text-xs px-3 py-2 mx-4 mt-3 rounded-sm border"
          style={{ background: "var(--surface-elev)", color: "var(--accent)", borderColor: "var(--border-default)" }}
        >
          Install Heirloom to home screen
        </button>
      )}

      {home && (
        <div
          className="mx-4 mt-3 text-xs px-3 py-2 rounded-sm flex items-start gap-2"
          style={{
            background: "var(--surface-elev)",
            color: online ? "#527a3d" : "var(--text-muted)",
            border: "1px solid var(--border-default)",
          }}
          data-testid="mobile-home-banner"
        >
          <Home className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span>{home.message}</span>
        </div>
      )}

      <main className="flex-1 px-4 py-4" data-testid="mobile-main">
        <Outlet context={{ home }} />
      </main>

      <nav
        className="fixed bottom-0 left-0 right-0 border-t backdrop-blur"
        style={{
          background: "rgba(18,17,16,0.92)",
          borderColor: "var(--border-default)",
          paddingBottom: "env(safe-area-inset-bottom)",
        }}
        data-testid="mobile-tabbar"
      >
        <div className="grid grid-cols-5 h-16">
          {TABS.map((t) => {
            const active = loc.pathname.startsWith(t.to);
            const Icon = t.icon;
            return (
              <NavLink
                key={t.to}
                to={t.to}
                data-testid={t.tid}
                className="flex flex-col items-center justify-center gap-1 transition-colors"
                style={{ color: active ? "var(--accent)" : "var(--text-muted)" }}
              >
                <Icon className="w-5 h-5" />
                <span className="text-[11px] font-medium">{t.label}</span>
              </NavLink>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
