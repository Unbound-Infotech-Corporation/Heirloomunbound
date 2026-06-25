import { motion } from "framer-motion";
import { ArrowRight, Heart, MessageCircleHeart, Mic } from "lucide-react";
import { Link } from "react-router-dom";

export default function Landing() {
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

      <header className="relative z-10 px-10 lg:px-20 py-8 flex justify-between items-center">
        <div>
          <div className="overline mb-1">est. {new Date().getFullYear()}</div>
          <div className="font-serif text-2xl" style={{ color: "var(--text-primary)" }}>
            Heirloom
          </div>
        </div>
        <Link
          to="/login"
          data-testid="landing-signin-link"
          className="text-sm tracking-wide hover:text-[var(--accent)] transition-colors"
          style={{ color: "var(--text-secondary)" }}
        >
          Sign in
        </Link>
      </header>

      <section className="relative z-10 px-10 lg:px-20 pt-16 lg:pt-24 max-w-6xl">
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
            A private archive of your voice, memories, beliefs, and the things you most want your son and family to remember. Over time, it becomes a digital twin they can sit with, listen to, and ask the questions they never got to ask.
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
              href="#how"
              data-testid="landing-cta-how"
              className="inline-flex items-center gap-2 px-7 py-4 rounded-sm font-medium text-sm tracking-wide transition-colors"
              style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            >
              How it works
            </a>
          </div>
        </motion.div>
      </section>

      <section id="how" className="relative z-10 px-10 lg:px-20 mt-32 lg:mt-44 max-w-6xl">
        <div className="overline mb-4">the practice</div>
        <h2 className="font-serif text-3xl lg:text-4xl mb-16 max-w-2xl">
          Three quiet rituals. A lifetime of you, preserved.
        </h2>

        <div className="grid md:grid-cols-3 gap-10 lg:gap-14">
          {[
            {
              icon: MessageCircleHeart,
              title: "Sit with the interviewer",
              body:
                "A patient AI biographer asks one careful question at a time, drawing out the stories only you can tell.",
            },
            {
              icon: Mic,
              title: "Speak into the silence",
              body:
                "Press record and talk. Your voice journals are transcribed and folded into the archive — the way you actually sound, the way you actually think.",
            },
            {
              icon: Heart,
              title: "Be a continuation",
              body:
                "Designate the people you trust. Years from now, they sit with your twin and ask what they wish they had.",
            },
          ].map((step, i) => {
            const Icon = step.icon;
            return (
              <motion.div
                key={step.title}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.8, delay: i * 0.15, ease: "easeOut" }}
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

      <section className="relative z-10 px-10 lg:px-20 mt-32 lg:mt-44 max-w-4xl">
        <div className="surface p-10 lg:p-14 rounded-sm">
          <div className="overline mb-4">a note on what this is, and isn't</div>
          <p className="font-serif text-2xl lg:text-3xl leading-snug" style={{ color: "var(--text-primary)" }}>
            Heirloom does not pretend to be you. It collects the truest pieces of you — in your words, in your voice — so the people you love can keep being held by them.
          </p>
        </div>
      </section>

      <footer
        className="relative z-10 px-10 lg:px-20 mt-32 py-10 border-t flex flex-wrap gap-6 justify-between items-center"
        style={{ borderColor: "var(--border-default)" }}
      >
        <div className="overline">heirloom · a continuation of you</div>
        <div className="flex gap-6 text-xs" style={{ color: "var(--text-muted)" }}>
          <span>built with care</span>
          <span>private by default</span>
        </div>
      </footer>
    </div>
  );
}
