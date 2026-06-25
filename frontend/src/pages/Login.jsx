import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
export default function Login() {
  const handleGoogle = () => {
    const redirectUrl = window.location.origin + "/dashboard";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2" style={{ background: "var(--bg-base)" }}>
      <div
        className="hidden lg:block relative"
        style={{
          backgroundImage:
            "url('https://images.unsplash.com/photo-1728506972831-193841eb2961?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAzMzl8MHwxfHNlYXJjaHwxfHxvbGQlMjBsaWJyYXJ5JTIwZGFyayUyMGFjYWRlbWlhfGVufDB8fHx8MTc4MjM1NzM4NXww&ixlib=rb-4.1.0&q=85')",
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(135deg, rgba(18,17,16,0.4), rgba(18,17,16,0.9))",
          }}
        />
        <div className="absolute bottom-12 left-12 right-12 z-10">
          <div className="overline mb-3">the archive of you</div>
          <p
            className="font-serif text-3xl leading-snug max-w-md"
            style={{ color: "var(--text-primary)" }}
          >
            "What I would give for one more conversation with him." — Begin so they never have to say that.
          </p>
        </div>
      </div>

      <div className="flex flex-col justify-center px-10 lg:px-20 py-16">
        <Link to="/" className="overline mb-10 inline-block" data-testid="login-brand-link">
          ← Heirloom
        </Link>
        <div className="max-w-md">
          <h1
            className="font-serif text-5xl font-light leading-[1.05] tracking-tight mb-5"
            style={{ color: "var(--text-primary)" }}
          >
            Welcome back.
          </h1>
          <p className="text-base mb-12" style={{ color: "var(--text-secondary)" }}>
            Continue your archive, or begin a new one. Your stories stay private to you and the heirs you choose.
          </p>

          <button
            onClick={handleGoogle}
            data-testid="login-google-button"
            className="w-full flex items-center justify-between px-6 py-5 transition-colors group"
            style={{
              background: "var(--accent)",
              color: "var(--text-inverse)",
              borderRadius: "2px",
            }}
          >
            <span className="text-sm font-medium tracking-wide">Continue with Google</span>
            <ArrowRight className="h-4 w-4 group-hover:translate-x-1 transition-transform" />
          </button>

          <div
            className="mt-10 pt-8 border-t text-xs leading-relaxed"
            style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}
          >
            By signing in you agree that Heirloom will store your archive privately. Your data is never used to train external models.
          </div>
        </div>
      </div>
    </div>
  );
}
