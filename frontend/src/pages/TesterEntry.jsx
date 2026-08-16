import { useEffect } from "react";
import { ArrowRight, Gift } from "lucide-react";
import { setTester } from "@/lib/tester";
import { usePageMeta } from "@/lib/usePageMeta";

// Shareable tester entry. Marks this browser as a tester (hides all Buy CTAs)
// then invites them to sign in — full access, no payment.
export default function TesterEntry() {
  usePageMeta({
    title: "You're invited to test Heirloom",
    description: "Free tester access to Heirloom — sign in with Google, no payment needed.",
  });

  useEffect(() => {
    setTester(true);
  }, []);

  const handleGoogle = () => {
    const redirectUrl = window.location.origin + "/today";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center px-6"
      style={{ background: "var(--bg-base)" }}
      data-testid="tester-entry"
    >
      <div className="w-full max-w-md text-center">
        <div
          className="inline-flex items-center justify-center h-12 w-12 rounded-sm mb-6"
          style={{ background: "var(--accent-muted, rgba(212,163,115,0.12))", border: "1px solid var(--accent)", color: "var(--accent)" }}
        >
          <Gift className="h-5 w-5" />
        </div>
        <div className="overline mb-3">you're invited</div>
        <h1 className="font-serif text-4xl font-light tracking-tight mb-4">
          Test Heirloom — on the house.
        </h1>
        <p className="text-base mb-8" style={{ color: "var(--text-secondary)" }}>
          You've been invited to try the full experience. Everything's unlocked and
          completely free while you test — no payment, no card, nothing to buy.
        </p>
        <button
          type="button"
          onClick={handleGoogle}
          data-testid="tester-continue"
          className="w-full inline-flex items-center justify-center gap-2 px-6 py-4 rounded-sm text-base font-medium tracking-wide transition-opacity hover:opacity-95"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          Sign in with Google <ArrowRight className="h-4 w-4" />
        </button>
        <p className="text-xs mt-5" style={{ color: "var(--text-muted)" }}>
          Sign in creates your private archive. Your data is never used to train external models.
        </p>
      </div>
    </div>
  );
}
