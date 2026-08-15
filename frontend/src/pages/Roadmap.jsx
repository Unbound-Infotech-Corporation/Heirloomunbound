import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Circle, Loader2 } from "lucide-react";
import { usePageMeta } from "@/lib/usePageMeta";

// Public roadmap — set by main agent, in sync with PRD.md. Kept intentionally
// simple: 3 buckets, no voting/upvoting yet (that's Roadmap v2).

const ROADMAP = [
  {
    bucket: "shipped",
    label: "Already yours",
    tint: "var(--success, #7da06f)",
    items: [
      { title: "Voice cloning (ElevenLabs)", detail: "Sit down for six minutes and read a short script. Your voice, on tap." },
      { title: "Personality archive & interviewer", detail: "The twin asks; you answer. Every answer becomes part of you." },
      { title: "Twin conversations", detail: "Sit with your own twin. Sealed by end-to-end auth." },
      { title: "Sealed letters", detail: "Write to people you love. Delivered on the date you choose." },
      { title: "Focus mode", detail: "One goal, many steps — your twin plans, you approve, it runs through your PC." },
      { title: "Windows companion (always-on)", detail: "Wake word, quick capture, on-PC vault." },
      { title: "Photo → Story", detail: "Any photo, spoken into a memory in your voice." },
      { title: "Avatar Studio", detail: "Pin a face to the twin — talking-head videos, body sheet, and local Pinokio/ComfyUI recipes." },
      { title: "Abilities framework", detail: "Turn skills on and off — web search, PC control, smart home, and more." },
    ],
  },
  {
    bucket: "building",
    label: "On the workbench",
    tint: "var(--accent)",
    items: [
      { title: "Local AI — run everything on your own PC", detail: "Pinokio · Ollama · LM Studio · ComfyUI. Nothing leaves the machine." },
      { title: "Multi-provider AI router + usage tracking", detail: "Connect OpenAI, Anthropic, Gemini, Groq. The twin picks the best model per task; a live dashboard shows how much of each free tier you have left." },
      { title: "Phone calling (Twilio)", detail: "Your twin gets a real phone number. Answers in your voice. Transcribes both sides." },
      { title: "Semantic memory search", detail: "Ask by meaning, not keyword. The twin actually remembers." },
      { title: "Photo restoration", detail: "Old family photos come back sharp — before they enter the archive." },
      { title: "Speaker-diarized video import", detail: "Drop in a family video. It splits by speaker automatically." },
      { title: "Handwriting OCR", detail: "Photograph grandma's letters — they become searchable in her voice." },
      { title: "Old-audio cleanup", detail: "Rescue noisy voice memos into studio-clean recordings." },
      { title: "Emotion-aware TTS", detail: "The twin can whisper, laugh, choke up. Voice memories that feel alive." },
      { title: "LivePortrait avatars", detail: "Look-at-you on the home PC via Pinokio. EchoMimic / Sonic / WAN for talking clips. D-ID remains the paid fallback." },
    ],
  },
  {
    bucket: "queued",
    label: "Coming after",
    tint: "var(--text-muted)",
    items: [
      { title: "LoRA personality fine-tuning", detail: "The twin trained on your writing — sounds like you, not Claude imitating you. The single biggest quality upgrade available." },
      { title: "Discord ingestion", detail: "Passive personality capture from the chats you already have." },
      { title: "Home Assistant control", detail: "Lights, plugs, scenes — commanded through the twin." },
      { title: "Yearbook PDF", detail: "A printable book of your life, generated from the archive." },
      { title: "Family-tree graph", detail: "Every memory linked to the people it involves." },
      { title: "Full archive export", detail: "PDF memoir and raw JSON — always." },
    ],
  },
];

const ICON = {
  shipped: CheckCircle2,
  building: Loader2,
  queued: Circle,
};

export default function Roadmap() {
  usePageMeta({
    title: "Roadmap · Heirloom",
    description: "What Heirloom is, what we're building, and what comes after. Built with our early owners in the room.",
  });

  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="min-h-screen" style={{ background: "var(--bg-canvas)", color: "var(--text-primary)" }} data-testid="roadmap-root">
      <div className="max-w-4xl mx-auto px-5 sm:px-10 lg:px-16 py-16">
        <Link
          to="/"
          className="inline-flex items-center gap-2 text-sm mb-10"
          style={{ color: "var(--text-muted)" }}
          data-testid="roadmap-back"
        >
          <ArrowLeft className="h-4 w-4" /> back to landing
        </Link>

        <header className="mb-14">
          <div className="overline mb-3 flex items-center gap-2">
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ background: "var(--accent)", boxShadow: "0 0 0 4px rgba(232,169,92,0.18)" }}
            />
            public roadmap · updated {now.toLocaleDateString(undefined, { month: "long", year: "numeric" })}
          </div>
          <h1 className="font-serif text-4xl sm:text-5xl lg:text-6xl font-light leading-tight">
            Built with you, not for you.
          </h1>
          <p className="mt-5 text-base lg:text-lg max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            Heirloom is meant to hold a person&apos;s voice, values, and memories across
            generations. We&apos;d rather build it slowly and get it right than ship
            something disposable. Here&apos;s exactly where we are — every idea from
            early owners is on this list.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <a
              href="mailto:hello@heirloomunbound.com?subject=Heirloom%20—%20idea%20for%20the%20roadmap"
              data-testid="roadmap-suggest"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-sm text-sm font-medium"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              Suggest a feature
            </a>
            <Link
              to="/support"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-sm text-sm"
              style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
              data-testid="roadmap-feedback"
            >
              Send feedback
            </Link>
          </div>
        </header>

        {ROADMAP.map((section) => {
          const Icon = ICON[section.bucket];
          return (
            <section key={section.bucket} className="mb-14" data-testid={`roadmap-${section.bucket}`}>
              <div className="flex items-center gap-3 mb-6">
                <span className="h-px flex-1" style={{ background: "var(--border-default)" }} />
                <span
                  className="text-xs uppercase tracking-widest px-3 py-1 rounded-sm"
                  style={{ color: section.tint, border: `1px solid ${section.tint}` }}
                >
                  {section.label}
                </span>
                <span className="h-px flex-1" style={{ background: "var(--border-default)" }} />
              </div>
              <ul className="space-y-4">
                {section.items.map((item, i) => (
                  <li
                    key={`${section.bucket}-${i}`}
                    className="flex items-start gap-4 p-5 rounded-sm"
                    style={{
                      border: "1px solid var(--border-default)",
                      background: section.bucket === "building" ? "rgba(232,169,92,0.03)" : "transparent",
                    }}
                    data-testid={`roadmap-item-${section.bucket}-${i}`}
                  >
                    <Icon
                      className={`h-5 w-5 mt-0.5 shrink-0 ${section.bucket === "building" ? "animate-spin" : ""}`}
                      style={{ color: section.tint, animationDuration: "3s" }}
                    />
                    <div className="min-w-0">
                      <div className="text-base font-medium" style={{ color: "var(--text-primary)" }}>
                        {item.title}
                      </div>
                      <div className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                        {item.detail}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}

        <footer className="mt-20 pt-8" style={{ borderTop: "1px solid var(--border-default)" }}>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            Miss something you&apos;d hand to your grandchildren?{" "}
            <a
              href="mailto:hello@heirloomunbound.com"
              style={{ color: "var(--accent)" }}
            >
              hello@heirloomunbound.com
            </a>{" "}
            — we read every one.
          </p>
        </footer>
      </div>
    </div>
  );
}
