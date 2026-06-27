import { motion } from "framer-motion";
import { ArrowRight, Brain, Heart, Lock, MessageCircleHeart, Mic, MonitorDown, Server } from "lucide-react";
import { Link } from "react-router-dom";
import { usePageMeta } from "../lib/usePageMeta";

export default function Landing() {
  usePageMeta({
    title: "Heirloom — Build the version of yourself that gets to stay.",
    description:
      "A private archive of your voice, memories, beliefs, and stories. A daily AI biographer that becomes a digital twin your family can sit with one day. $79 lifetime. By Unbound Infotech.",
  });
  return (
    <div className="min-h-screen relative overflow-hidden" style={{ background: "var(--bg-base)" }}>
      <div
        className="absolute inset-0 opacity-40"
        style={{
          backgroundImage:
            "url('https://images.pexels.com/photos/9665179/pexels-photo-9665179.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940')",
          backgroundSize: "cover",
          backgroundPosition: "center",
          maskImage: "linear-gradient(to bottom, rgba(0,0,0,0.9), rgba(0,0,0,0.2) 60%, rgba(0,0,0,0))",
          WebkitMaskImage: "linear-gradient(to bottom, rgba(0,0,0,0.9), rgba(0,0,0,0.2) 60%, rgba(0,0,0,0))",
        }}
      />
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(circle at 30% 20%, rgba(212,163,115,0.12), transparent 50%), linear-gradient(to bottom, rgba(18,17,16,0.5), rgba(18,17,16,0.95))",
        }}
      />

      <header className="relative z-10 px-5 sm:px-10 lg:px-20 py-8 flex justify-between items-center">
        <div>
          <div className="overline mb-1">an unbound infotech product</div>
          <div className="font-serif text-2xl" style={{ color: "var(--text-primary)" }}>
            Heirloom
          </div>
        </div>
        <div className="flex items-center gap-7 text-sm">
          <a href="#how" data-testid="landing-how-link" className="hidden sm:inline" style={{ color: "var(--text-secondary)" }}>How it works</a>
          <a href="#windows" data-testid="landing-download-link" className="hidden sm:inline" style={{ color: "var(--text-secondary)" }}>Windows app</a>
          <Link
            to="/buy"
            data-testid="landing-buy-link"
            className="hidden sm:inline tracking-wide"
            style={{ color: "var(--accent)" }}
          >
            $79 — Buy lifetime
          </Link>
          <Link
            to="/login"
            data-testid="landing-signin-link"
            className="tracking-wide hover:text-[var(--accent)] transition-colors"
            style={{ color: "var(--text-secondary)" }}
          >
            Sign in
          </Link>
        </div>
      </header>

      {/* HERO */}
      <section className="relative z-10 px-5 sm:px-10 lg:px-20 pt-16 lg:pt-24 max-w-6xl">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1.1, ease: "easeOut" }}
        >
          <div className="overline mb-6">a continuation of you</div>
          <h1
            className="font-serif text-5xl sm:text-6xl lg:text-7xl font-light tracking-tight leading-[1.05] max-w-4xl"
            style={{ color: "var(--text-primary)" }}
          >
            Build the version of yourself
            <br />
            <em style={{ color: "var(--accent)", fontStyle: "italic" }}>that gets to stay.</em>
          </h1>
          <p
            className="mt-8 max-w-2xl text-lg leading-relaxed"
            style={{ color: "var(--text-secondary)" }}
          >
            A private archive of your voice, memories, beliefs, and the things you most want your family to remember. A daily assistant that becomes a digital twin they can sit with after you're gone.
          </p>

          <div className="mt-12 flex flex-wrap gap-4">
            <Link
              to="/login"
              data-testid="landing-cta-begin"
              className="inline-flex items-center gap-2 px-7 py-4 rounded-sm font-medium text-sm tracking-wide transition-colors"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              Begin your archive <ArrowRight className="h-4 w-4" />
            </Link>
            <a
              href="#windows"
              data-testid="landing-cta-windows"
              className="inline-flex items-center gap-2 px-7 py-4 rounded-sm font-medium text-sm tracking-wide transition-colors"
              style={{ border: "1px solid var(--accent)", color: "var(--accent)" }}
            >
              <MonitorDown className="h-4 w-4" /> Download for Windows
            </a>
          </div>
        </motion.div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how" className="relative z-10 px-5 sm:px-10 lg:px-20 mt-32 lg:mt-44 max-w-6xl">
        <div className="overline mb-4">the practice</div>
        <h2 className="font-serif text-3xl lg:text-4xl mb-16 max-w-2xl">
          A daily assistant that becomes a lasting heirloom.
        </h2>

        <div className="grid md:grid-cols-3 gap-10 lg:gap-14">
          {[
            {
              icon: Brain,
              title: "Capture in seconds",
              body:
                "A always-visible quick-capture bar turns any thought, reminder, or memory into the right kind of entry. The Twin sorts as you go.",
            },
            {
              icon: MessageCircleHeart,
              title: "Sit with the biographer",
              body:
                "A patient AI biographer asks one careful question at a time, drawing out the stories only you can tell.",
            },
            {
              icon: Mic,
              title: "Speak into the silence",
              body:
                "Press a key on your PC and talk. Your voice is transcribed and folded into the archive — the way you actually sound, the way you actually think.",
            },
            {
              icon: Heart,
              title: "Become a continuation",
              body:
                "Designate the people you trust. Years from now, they sit with your twin and ask what they always wished they had.",
            },
          ].map((step, i) => {
            const Icon = step.icon;
            return (
              <motion.div
                key={step.title}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.8, delay: i * 0.12, ease: "easeOut" }}
                className="border-l pl-8 py-2"
                style={{ borderColor: "var(--border-default)" }}
                data-testid={`landing-ritual-${i}`}
              >
                <Icon className="h-6 w-6 mb-5" style={{ color: "var(--accent)" }} />
                <div className="overline mb-2">No. {String(i + 1).padStart(2, "0")}</div>
                <h3 className="font-serif text-2xl mb-3">{step.title}</h3>
                <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  {step.body}
                </p>
              </motion.div>
            );
          })}
        </div>
      </section>

      {/* WINDOWS COMPANION */}
      <section id="windows" className="relative z-10 px-5 sm:px-10 lg:px-20 mt-32 lg:mt-44 max-w-6xl">
        <div className="grid lg:grid-cols-2 gap-14 items-center">
          <div>
            <div className="overline mb-4">windows companion</div>
            <h2 className="font-serif text-3xl lg:text-4xl mb-6 leading-tight">
              Always on the desk. Always at your shoulder.
            </h2>
            <p className="text-base leading-relaxed mb-6" style={{ color: "var(--text-secondary)" }}>
              A tiny Python companion runs on your PC. Hold Ctrl+Space and talk — your Twin answers in your voice. Connect local folders, smart-home webhooks, or scripts so the Twin can actually <em>do</em> things for you, not just remember.
            </p>
            <ul className="space-y-3 mb-8 text-sm" style={{ color: "var(--text-secondary)" }}>
              <li className="flex items-start gap-3"><span style={{ color: "var(--accent)" }}>·</span> Push-to-talk hotkey, hands-free</li>
              <li className="flex items-start gap-3"><span style={{ color: "var(--accent)" }}>·</span> Reminders read aloud at their due time</li>
              <li className="flex items-start gap-3"><span style={{ color: "var(--accent)" }}>·</span> Syncs local folders into your archive (journals, drafts, notes)</li>
              <li className="flex items-start gap-3"><span style={{ color: "var(--accent)" }}>·</span> Built for a 5090-class PC — but works fine on anything modern</li>
            </ul>
            <Link
              to="/login"
              data-testid="landing-cta-windows2"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-sm font-medium text-sm tracking-wide"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              <MonitorDown className="h-4 w-4" /> Sign in & download
              <ArrowRight className="h-4 w-4 ml-1" />
            </Link>
            <p className="mt-4 text-xs" style={{ color: "var(--text-muted)" }}>
              The download is personalised to your account — sign in once to grab a token-bound copy.
            </p>
          </div>

          <div
            className="surface p-8 font-mono text-xs leading-relaxed"
            style={{ background: "var(--bg-surface)", border: "1px solid var(--border-default)" }}
            data-testid="landing-companion-snippet"
          >
            <div className="overline mb-3">requirements</div>
            <div style={{ color: "var(--text-secondary)" }}>· Windows 10/11, macOS, or Linux</div>
            <div style={{ color: "var(--text-secondary)" }} className="mb-4">· Python 3.10+</div>
            <div className="overline mb-3">install</div>
            <pre className="whitespace-pre-wrap mb-4" style={{ color: "var(--accent)" }}>
{`pip install requests sounddevice
   soundfile numpy pynput`}
            </pre>
            <div className="overline mb-3">run</div>
            <pre className="whitespace-pre-wrap" style={{ color: "var(--accent)" }}>
{`python heirloom_companion.py`}
            </pre>
          </div>
        </div>
      </section>

      {/* QUOTE */}
      <section className="relative z-10 px-5 sm:px-10 lg:px-20 mt-32 lg:mt-44 max-w-4xl">
        <div className="surface p-10 lg:p-14 rounded-sm">
          <div className="overline mb-4">a note on what this is, and isn't</div>
          <p className="font-serif text-2xl lg:text-3xl leading-snug" style={{ color: "var(--text-primary)" }}>
            Heirloom does not pretend to be you. It collects the truest pieces of you — in your words, in your voice — so the people you love can keep being held by them.
          </p>
        </div>
      </section>

      {/* TRUST */}
      <section className="relative z-10 px-5 sm:px-10 lg:px-20 mt-24 max-w-4xl text-center">
        <div className="flex flex-wrap gap-8 justify-center items-center" style={{ color: "var(--text-muted)" }}>
          <span className="inline-flex items-center gap-2 text-xs"><Lock className="h-3.5 w-3.5" /> private by default</span>
          <span className="inline-flex items-center gap-2 text-xs"><Server className="h-3.5 w-3.5" /> hosted on dedicated GPU infrastructure</span>
          <span className="text-xs">never used to train external models</span>
        </div>
      </section>

      {/* FOOTER */}
      <footer
        className="relative z-10 px-5 sm:px-10 lg:px-20 mt-32 py-10 border-t flex flex-wrap gap-6 justify-between items-center"
        style={{ borderColor: "var(--border-default)" }}
      >
        <div>
          <div className="overline mb-1">heirloom · a continuation of you</div>
          <a
            href="https://unboundinfotech.com"
            target="_blank"
            rel="noreferrer"
            className="text-xs hover:text-[var(--accent)]"
            style={{ color: "var(--text-muted)" }}
            data-testid="landing-unbound-link"
          >
            built by Unbound Infotech Corporation →
          </a>
        </div>
        <div className="flex gap-6 text-xs flex-wrap" style={{ color: "var(--text-muted)" }}>
          <Link to="/privacy" className="hover:text-[var(--accent)] transition-colors" data-testid="landing-privacy">Privacy</Link>
          <Link to="/terms" className="hover:text-[var(--accent)] transition-colors" data-testid="landing-terms">Terms</Link>
          <Link to="/refunds" className="hover:text-[var(--accent)] transition-colors" data-testid="landing-refunds">Refunds</Link>
          <Link to="/support" className="hover:text-[var(--accent)] transition-colors" data-testid="landing-support">Support</Link>
          <span>private by default</span>
        </div>
      </footer>
    </div>
  );
}
