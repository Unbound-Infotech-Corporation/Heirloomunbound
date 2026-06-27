import { useState } from "react";
import { ArrowRight, BookOpen, MessageCircleHeart, Sparkles, Users, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

const STEPS = [
  {
    Icon: BookOpen,
    overline: "step 1 of 4",
    title: "Capture in seconds.",
    body: "Use the Quick Capture bar at the top of every page to drop in a memory, value, story, or piece of advice. The smallest thought belongs here too.",
    cta: "Show me",
    target: "/library",
  },
  {
    Icon: MessageCircleHeart,
    overline: "step 2 of 4",
    title: "Sit with the biographer.",
    body: "The Interviewer asks you gentle, intelligent questions — the kind a careful biographer would. Each answer becomes part of your archive.",
    cta: "Open the Interviewer",
    target: "/interviewer",
  },
  {
    Icon: Sparkles,
    overline: "step 3 of 4",
    title: "Speak to your Twin.",
    body: "Once your archive has some shape, the Twin replies in your voice and in your words. You can also click \u201CPlay as video\u201D to see your face speaking.",
    cta: "Meet the Twin",
    target: "/twin",
  },
  {
    Icon: Users,
    overline: "step 4 of 4",
    title: "Leave it for them.",
    body: "Add the people you love as heirs and write sealed letters that reach them one day. This is the part that lasts.",
    cta: "Set up an heir",
    target: "/heirs",
  },
];

export default function TourOverlay() {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();
  const [idx, setIdx] = useState(0);
  const [closing, setClosing] = useState(false);

  // Only render once on first login. Backed by users.tour_completed.
  if (!user || user.tour_completed || closing) return null;

  const dismiss = async (navigateTo) => {
    setClosing(true);
    setUser({ ...user, tour_completed: true });
    try {
      await api.post("/auth/me/tour-complete");
    } catch {
      /* ignore — the local state is already updated; we'll retry on next /auth/me */
    }
    if (navigateTo) navigate(navigateTo);
  };

  const next = () => {
    if (idx < STEPS.length - 1) {
      setIdx(idx + 1);
    } else {
      dismiss(STEPS[idx].target);
    }
  };

  const step = STEPS[idx];
  const StepIcon = step.Icon;

  return (
    <div
      data-testid="tour-overlay"
      className="fixed inset-0 z-50 flex items-center justify-center px-6"
      style={{ background: "rgba(8, 7, 6, 0.78)", backdropFilter: "blur(8px)" }}
    >
      <div
        className="relative max-w-xl w-full p-10 lg:p-12 rounded-sm"
        style={{
          background: "var(--bg-surface)",
          border: "1px solid var(--border-default)",
          boxShadow: "0 30px 90px rgba(0,0,0,0.55)",
        }}
      >
        <button
          onClick={() => dismiss(null)}
          data-testid="tour-skip"
          className="absolute top-5 right-5 p-1.5 rounded-sm transition-colors hover:text-[var(--text-primary)]"
          style={{ color: "var(--text-muted)" }}
          aria-label="Skip tour"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="flex items-center gap-4 mb-7">
          <div
            className="h-12 w-12 flex items-center justify-center rounded-sm"
            style={{ background: "var(--accent-muted)", border: "1px solid var(--accent)" }}
          >
            <StepIcon className="h-5 w-5" style={{ color: "var(--accent)" }} />
          </div>
          <div>
            <div className="overline mb-1">{step.overline}</div>
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>
              welcome to Heirloom
            </div>
          </div>
        </div>

        <h2
          className="font-serif font-light tracking-tight mb-5"
          style={{ color: "var(--text-primary)", fontSize: "2.25rem", lineHeight: 1.15 }}
        >
          {step.title}
        </h2>
        <p className="text-base leading-relaxed mb-10" style={{ color: "var(--text-secondary)" }}>
          {step.body}
        </p>

        <div className="flex items-center justify-between">
          <div className="flex gap-1.5" data-testid="tour-progress">
            {STEPS.map((_, i) => (
              <span
                key={i}
                className="h-1.5 rounded-full transition-all"
                style={{
                  width: i === idx ? 24 : 8,
                  background: i <= idx ? "var(--accent)" : "var(--border-default)",
                }}
              />
            ))}
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => dismiss(null)}
              data-testid="tour-skip-text"
              className="text-xs transition-colors hover:text-[var(--text-primary)]"
              style={{ color: "var(--text-muted)" }}
            >
              Skip the tour
            </button>
            <button
              onClick={next}
              data-testid="tour-next"
              className="inline-flex items-center gap-2 px-5 py-2.5 text-sm rounded-sm transition-opacity hover:opacity-90"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              {idx === STEPS.length - 1 ? step.cta : "Next"}
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
