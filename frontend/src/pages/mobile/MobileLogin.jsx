import { ArrowRight } from "lucide-react";
import { usePageMeta } from "@/lib/usePageMeta";

/**
 * Phone-app sign-in. One tap opens Google. We never see that password.
 * After Google, AuthCallback lands back in /m (not the desktop Today page).
 */
export default function MobileLogin() {
  usePageMeta({
    title: "Sign in with Google — Heirloom",
    description: "Sign in with Google on this phone. Heirloom never sees that password.",
  });

  const handleGoogle = () => {
    try {
      sessionStorage.setItem("heirloom_after_google", "phone");
    } catch {
      /* ignore */
    }
    const redirectUrl = window.location.origin + "/m";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div
      className="min-h-screen flex flex-col justify-center px-5"
      style={{
        background: "var(--bg-base)",
        color: "var(--text-primary)",
        paddingTop: "env(safe-area-inset-top)",
        paddingBottom: "env(safe-area-inset-bottom)",
      }}
      data-testid="mobile-login"
    >
      <div className="max-w-md mx-auto w-full">
        <div className="overline mb-3">heirloom on this phone</div>
        <h1 className="font-serif text-4xl font-light tracking-tight mb-4">
          Sign in with Google
        </h1>
        <p className="text-base mb-8 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          Tap the button. A Google page opens. Sign in there. Then this phone can talk to your twin,
          look at the screen, and use Write. Heirloom never sees that password.
        </p>
        <button
          type="button"
          onClick={handleGoogle}
          data-testid="mobile-login-google-button"
          className="w-full flex items-center justify-between px-6 py-5 transition-colors"
          style={{
            background: "#c45c38",
            color: "#fff8e4",
            borderRadius: "8px",
            fontWeight: 800,
          }}
        >
          <span className="text-base tracking-wide">Sign in with Google</span>
          <ArrowRight className="h-5 w-5" />
        </button>
        <p className="text-xs mt-6 leading-relaxed" style={{ color: "var(--text-muted)" }}>
          We never ask for a Google, Apple, Microsoft, or phone password. Spelling in Write still
          works after you sign in. On iPhone, this is the Heirloom app — Apple does not let us
          install a keyboard.
        </p>
      </div>
    </div>
  );
}
