import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Camera, Check, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/usePageMeta";

// Photo -> Story: upload a photo, the twin looks at it and asks a few personal
// questions, then weaves your answers into a first-person memory in your archive.
export default function PhotoStory() {
  usePageMeta({
    title: "Photo → Story · Heirloom",
    description: "Turn a photo into a written memory your twin remembers forever.",
  });

  const [step, setStep] = useState("upload"); // upload | questions | done
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);
  const [session, setSession] = useState(null); // { photo_story_id, description, questions }
  const [answers, setAnswers] = useState([]);
  const [story, setStory] = useState(null); // { entry_id, title, content }
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef(null);

  const handleFile = async (file) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast.error("Please choose an image (JPEG or PNG).");
      return;
    }
    setPreview(URL.createObjectURL(file));
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await api.post("/photo-story/start", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setSession(data);
      setAnswers(new Array(data.questions.length).fill(""));
      setStep("questions");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't read that photo. Try another.");
      setPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const compose = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/photo-story/${session.photo_story_id}/compose`, { answers });
      setStory(data);
      setStep("done");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't compose the story.");
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setStep("upload");
    setPreview(null);
    setSession(null);
    setAnswers([]);
    setStory(null);
  };

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-3xl" data-testid="photo-story-root">
      <header className="mb-10">
        <div className="overline mb-3">grow your archive</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">Photo → Story</h1>
        <p className="mt-3 text-base max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          Drop in a photo. Your twin will look at it, ask you a few questions, and turn your answers
          into a written memory — saved forever in your archive.
        </p>
      </header>

      {step === "upload" && (
        <div
          className="rounded-sm flex flex-col items-center justify-center text-center cursor-pointer transition-colors py-20 px-6"
          style={{
            background: dragOver ? "var(--accent-muted, rgba(212,163,115,0.12))" : "var(--bg-surface)",
            border: `1px dashed ${dragOver ? "var(--accent)" : "var(--border-default)"}`,
          }}
          onClick={() => !busy && fileInput.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer?.files?.[0]); }}
          data-testid="photo-dropzone"
        >
          <input
            ref={fileInput}
            type="file"
            accept="image/*"
            className="hidden"
            data-testid="photo-input"
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
          {busy ? (
            <>
              <Loader2 className="h-8 w-8 animate-spin mb-4" style={{ color: "var(--accent)" }} />
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>Your twin is looking at the photo…</p>
            </>
          ) : (
            <>
              <Camera className="h-10 w-10 mb-4" style={{ color: "var(--text-muted)" }} />
              <p className="text-base" style={{ color: "var(--text-primary)" }}>Click or drop a photo here</p>
              <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>JPEG or PNG · a person, a place, a moment</p>
            </>
          )}
        </div>
      )}

      {step === "questions" && session && (
        <div className="grid md:grid-cols-[1fr_1.3fr] gap-8" data-testid="photo-questions">
          <div>
            {preview && (
              <img src={preview} alt="your upload" className="w-full rounded-sm mb-3" style={{ border: "1px solid var(--border-default)" }} />
            )}
            {session.description && (
              <p className="text-sm italic" style={{ color: "var(--text-muted)" }}>“{session.description}”</p>
            )}
          </div>
          <div>
            <div className="overline mb-4">a few questions</div>
            <div className="space-y-5">
              {session.questions.map((q, i) => (
                <div key={i}>
                  <label className="text-sm block mb-2" style={{ color: "var(--text-primary)" }}>{q}</label>
                  <textarea
                    rows={2}
                    value={answers[i] || ""}
                    onChange={(e) => setAnswers((a) => a.map((v, j) => (j === i ? e.target.value : v)))}
                    data-testid={`photo-answer-${i}`}
                    className="w-full px-3 py-2 text-sm rounded-sm resize-none"
                    style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
                    placeholder="in your own words…"
                  />
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={compose}
              disabled={busy || answers.every((a) => !a.trim())}
              data-testid="photo-compose"
              className="mt-6 inline-flex items-center gap-2 px-6 py-3 rounded-sm text-sm font-medium tracking-wide disabled:opacity-50"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              Weave it into a memory
            </button>
          </div>
        </div>
      )}

      {step === "done" && story && (
        <div data-testid="photo-story-result">
          <div className="surface p-8">
            {preview && (
              <img src={preview} alt="your memory" className="w-40 rounded-sm mb-6" style={{ border: "1px solid var(--border-default)" }} />
            )}
            <div className="overline mb-2 flex items-center gap-2" style={{ color: "var(--accent)" }}>
              <Check className="h-3.5 w-3.5" /> saved to your archive
            </div>
            <h2 className="font-serif text-3xl mb-4">{story.title}</h2>
            <p className="text-base leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
              {story.content}
            </p>
          </div>
          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={reset}
              data-testid="photo-another"
              className="inline-flex items-center gap-2 px-5 py-2.5 text-sm rounded-sm"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              <Camera className="h-4 w-4" /> Tell another
            </button>
            <Link
              to="/dashboard"
              data-testid="photo-view-archive"
              className="inline-flex items-center gap-2 px-5 py-2.5 text-sm rounded-sm"
              style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
            >
              View in archive <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
