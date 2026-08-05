import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Camera, History, Phone } from "lucide-react";

/**
 * Mobile PWA shell — bottom tab bar + safe-area padding for iOS.
 * Routes:
 *   /m           → default → redirect to /m/call
 *   /m/call      → in-app dialer + PSTN card
 *   /m/capture   → voice memo + photo capture
 *   /m/history   → recent calls + memories
 *
 * This shell is intentionally standalone from AppLayout — no sidebar, no
 * marketing header — so it feels like a native app when opened from the
 * Home Screen. It respects the safe-area insets on notched devices.
 */
const TABS = [
  { to: "/m/call",    label: "Call",    icon: Phone,   tid: "mobile-tab-call" },
  { to: "/m/capture", label: "Capture", icon: Camera,  tid: "mobile-tab-capture" },
  { to: "/m/history", label: "History", icon: History, tid: "mobile-tab-history" },
];

export default function MobileShell() {
  const loc = useLocation();
  const [installable, setInstallable] = useState(null);

  // Capture the beforeinstallprompt event so we can show a "Install app"
  // button in-app on Android/desktop. iOS Safari doesn't fire this and needs
  // the manual "Add to Home Screen" gesture — we show a hint for that too.
  useEffect(() => {
    const onPrompt = (e) => {
      e.preventDefault();
      setInstallable(e);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  const promptInstall = async () => {
    if (!installable) return;
    installable.prompt();
    await installable.userChoice;
    setInstallable(null);
  };

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

      <main className="flex-1 px-4 py-4" data-testid="mobile-main">
        <Outlet />
      </main>

      {/* Bottom tab bar */}
      <nav
        className="fixed bottom-0 left-0 right-0 border-t backdrop-blur"
        style={{
          background: "rgba(18,17,16,0.92)",
          borderColor: "var(--border-default)",
          paddingBottom: "env(safe-area-inset-bottom)",
        }}
        data-testid="mobile-tabbar"
      >
        <div className="grid grid-cols-3 h-16">
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
