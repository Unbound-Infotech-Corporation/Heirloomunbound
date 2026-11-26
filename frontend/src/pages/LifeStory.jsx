import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import HeirSharing from "../components/memory/HeirSharing";
import { api } from "../lib/api";

const btn = { border: "1px solid var(--border-default)", color: "var(--text-primary)" };
const primary = { background: "var(--accent)", color: "var(--text-inverse)" };
const SOURCE_LABEL = { interview: "Interview", photo: "Photo", messages: "Messages", letter: "Letter", document: "Document" };

function speak(text) {
  // On-device voices only, so the question never leaves this computer.
  const synth = typeof window !== "undefined" ? window.speechSynthesis : null;
  if (!synth || !text) return;
  const local = synth.getVoices().filter((v) => v.localService);
  if (!local.length) return;
  const utter = new SpeechSynthesisUtterance(text);
  utter.voice = local.find((v) => v.lang?.startsWith("en")) || local[0];
  utter.rate = 0.95;
  synth.cancel();
  synth.speak(utter);
}

function useRecorder(onText, setBusy, setError) {
  const recorder = useRef(null);
  const chunks = useRef([]);
  const [recording, setRecording] = useState(false);
  const toggle = async () => {
    if (recording && recorder.current) {
      recorder.current.stop();
      setRecording(false);
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser cannot record. Type the answer instead.");
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const media = new MediaRecorder(stream);
    chunks.current = [];
    media.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    media.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const body = new FormData();
      body.append("file", new Blob(chunks.current, { type: "audio/webm" }), "answer.webm");
      setBusy("Hearing the recording…");
      try {
        const { data } = await api.post("/memory-loop/transcribe", body);
        onText(data.transcript || "");
      } catch (err) {
        setError(err.response?.data?.detail || "Hearing could not read that recording. Type the answer instead.");
      } finally {
        setBusy("");
      }
    };
    recorder.current = media;
    media.start();
    setRecording(true);
  };
  return [recording, toggle];
}

function Interview({ setBusy, setError, onCards }) {
  const [plan, setPlan] = useState(null);
  const [state, setState] = useState(null);
  const [answer, setAnswer] = useState("");
  const [voiceOn, setVoiceOn] = useState(false);
  const [last, setLast] = useState(null);
  const append = (text) => setAnswer((prev) => (prev ? `${prev} ${text}` : text));
  const [recording, toggleRecord] = useRecorder(append, setBusy, setError);

  useEffect(() => {
    api.get("/life-story/plan").then(({ data }) => setPlan(data)).catch(() => {});
    api.get("/life-story/interview").then(({ data }) => setState(data)).catch(() => {});
  }, []);

  useEffect(() => {
    if (voiceOn && state?.current?.question) speak(state.current.question);
  }, [voiceOn, state?.current?.qid]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async (length, restart = false) => {
    setError("");
    const { data } = await api.post("/life-story/interview", { length, restart });
    setState(data);
  };

  const send = async () => {
    const words = answer.trim();
    if (!words || !state?.current) return;
    setBusy("Writing the memory card…");
    setError("");
    try {
      const { data } = await api.post("/life-story/interview/answer", { qid: state.current.qid, transcript: words });
      setState(data);
      setLast(data.card ? data.card : { too_short: true });
      setAnswer("");
      onCards();
    } catch (err) {
      setError(err.response?.data?.detail || "That answer was not saved. Try again.");
    } finally {
      setBusy("");
    }
  };

  const skip = async (body) => {
    const { data } = await api.post("/life-story/interview/skip", body);
    setState(data);
  };

  if (!state?.session) {
    return (
      <section className="surface p-6" data-testid="life-start">
        <p className="mb-4">
          A guided conversation about your life, one question at a time. Answer by voice or typing. Every answer becomes a
          memory card you review; nothing reaches your twin until you approve it. You can stop any time and pick up later.
        </p>
        <div className="flex flex-wrap gap-3">
          <button type="button" className="px-4 py-2 text-sm rounded-sm" style={primary} onClick={() => start("short")} data-testid="life-start-short">
            Short: about {plan?.short?.minutes || 30} minutes
          </button>
          <button type="button" className="px-4 py-2 text-sm rounded-sm" style={btn} onClick={() => start("full")} data-testid="life-start-full">
            Full: about {plan?.full?.minutes || 50} minutes
          </button>
        </div>
      </section>
    );
  }

  const { current, progress, session } = state;
  return (
    <div data-testid="life-interview">
      <div className="flex flex-wrap gap-2 mb-4 text-xs" data-testid="life-chapters">
        {progress.chapters.map((c) => (
          <span key={c.key} className="px-2 py-1 rounded-sm" style={{ ...btn, opacity: c.done === c.total ? 0.5 : 1, fontWeight: current?.chapter === c.key ? 600 : 400 }}>
            {c.title} {c.done}/{c.total}
          </span>
        ))}
      </div>
      <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }} data-testid="life-progress">
        {progress.answered} answered · about {progress.minutes_left} minutes left
      </p>
      {current ? (
        <>
          <section className="surface p-6 mb-4" data-testid="life-question">
            <div className="overline mb-3">{current.kind === "followup" ? "a little more" : current.chapter_title}</div>
            <p className="font-serif text-2xl leading-snug">{current.question}</p>
          </section>
          <textarea
            className="w-full min-h-[140px] p-3 text-base"
            style={{ background: "transparent", color: "var(--text-primary)", border: "1px solid var(--border-default)" }}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            aria-label="Your answer"
            data-testid="life-answer"
          />
          <div className="flex flex-wrap gap-3 mt-4 mb-6">
            <button type="button" className="px-4 py-2 text-sm rounded-sm" style={btn} onClick={toggleRecord} data-testid="life-voice">
              {recording ? "Stop and hear it" : "Answer by voice"}
            </button>
            <button type="button" className="px-4 py-2 text-sm rounded-sm disabled:opacity-50" style={primary} onClick={send} disabled={!answer.trim()} data-testid="life-send">
              Save and continue
            </button>
            <button type="button" className="px-4 py-2 text-sm rounded-sm" style={btn} onClick={() => skip({ qid: current.qid })} data-testid="life-skip">
              Skip this one
            </button>
            <button type="button" className="px-4 py-2 text-sm rounded-sm" style={btn} onClick={() => skip({ chapter: current.chapter })} data-testid="life-skip-chapter">
              Skip this chapter
            </button>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={voiceOn} onChange={(e) => setVoiceOn(e.target.checked)} data-testid="life-read-aloud" />
              Read questions aloud
            </label>
          </div>
        </>
      ) : (
        <section className="surface p-6 mb-4" data-testid="life-finished">
          <p className="mb-3">That's the whole interview. Review your cards below so your twin can use them.</p>
          <button type="button" className="px-4 py-2 text-sm rounded-sm" style={btn} onClick={() => start(session.length === "short" ? "full" : "short", true)}>
            Start another round
          </button>
        </section>
      )}
      {last ? (
        <p className="text-sm" data-testid="life-last">
          {last.too_short ? "That was short, so no card was made. That's fine." : `Saved as a card to review: “${last.title}”.`}
        </p>
      ) : null}
    </div>
  );
}

function Imports({ setBusy, setError, onCards }) {
  const [preview, setPreview] = useState(null);
  const [chatFile, setChatFile] = useState(null);
  const [me, setMe] = useState("");
  const [author, setAuthor] = useState("");
  const [photo, setPhoto] = useState({ file: null, caption: "", taken_at: "", place: "" });
  const [jobs, setJobs] = useState([]);
  const [note, setNote] = useState("");

  const loadJobs = useCallback(async () => {
    const { data } = await api.get("/life-story/imports");
    setJobs(data.imports || []);
    if ((data.imports || []).some((j) => j.status === "drafting")) onCards();
    return data.imports || [];
  }, [onCards]);

  useEffect(() => {
    loadJobs().catch(() => {});
    const t = setInterval(() => loadJobs().catch(() => {}), 4000);
    return () => clearInterval(t);
  }, [loadJobs]);

  const fail = (err, fallback) => setError(err.response?.data?.detail || fallback);

  const previewChat = async (file) => {
    setChatFile(file);
    setPreview(null);
    setError("");
    const body = new FormData();
    body.append("file", file);
    try {
      const { data } = await api.post("/life-story/import/messages/preview", body);
      setPreview(data);
      setMe(data.senders?.[0]?.name || "");
    } catch (err) {
      fail(err, "That chat export could not be read.");
    }
  };

  const importChat = async () => {
    const body = new FormData();
    body.append("file", chatFile);
    body.append("me", me);
    setBusy("Reading your messages…");
    try {
      await api.post("/life-story/import/messages", body);
      setPreview(null);
      setNote("Your messages are becoming cards. They show up under Review as they are ready.");
      await loadJobs();
    } catch (err) {
      fail(err, "Those messages were not imported.");
    } finally {
      setBusy("");
    }
  };

  const importDoc = async (file) => {
    const body = new FormData();
    body.append("file", file);
    body.append("author", author);
    setBusy("Reading the document…");
    try {
      await api.post("/life-story/import/document", body);
      setNote("The document is becoming cards. They show up under Review as they are ready.");
      await loadJobs();
    } catch (err) {
      fail(err, "That document was not imported.");
    } finally {
      setBusy("");
    }
  };

  const importPhoto = async () => {
    if (!photo.file) return;
    const body = new FormData();
    Object.entries(photo).forEach(([k, v]) => v && body.append(k, v));
    setBusy("Saving the photo…");
    try {
      const { data } = await api.post("/life-story/import/photo", body);
      if (data.needs_caption) {
        setPhoto((p) => ({ ...p, taken_at: p.taken_at || data.found?.taken_at || "" }));
        setError("Tell the story behind this photo first: who is in it, where, and what was happening.");
      } else {
        setPhoto({ file: null, caption: "", taken_at: "", place: "" });
        setNote("Photo saved with its story. Review the card below.");
        onCards();
      }
    } catch (err) {
      fail(err, "That photo was not saved.");
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="grid gap-6" data-testid="life-imports">
      <section className="surface p-6" data-testid="import-photo">
        <div className="overline mb-3">a photo and its story</div>
        <input type="file" accept="image/*" onChange={(e) => setPhoto({ ...photo, file: e.target.files?.[0] || null })} className="mb-3" />
        <textarea className="w-full min-h-[80px] p-2 mb-2" placeholder="Who is in it, where, and what was happening?" value={photo.caption} onChange={(e) => setPhoto({ ...photo, caption: e.target.value })} />
        <div className="flex gap-2 mb-3">
          <input className="flex-1 p-2" placeholder="When (optional)" value={photo.taken_at} onChange={(e) => setPhoto({ ...photo, taken_at: e.target.value })} />
          <input className="flex-1 p-2" placeholder="Where (optional)" value={photo.place} onChange={(e) => setPhoto({ ...photo, place: e.target.value })} />
        </div>
        <button type="button" className="px-4 py-2 text-sm rounded-sm disabled:opacity-50" style={primary} disabled={!photo.file} onClick={importPhoto}>Save photo</button>
      </section>

      <section className="surface p-6" data-testid="import-document">
        <div className="overline mb-3">letters and documents</div>
        <p className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>Text, Word, PDF, or web pages. A scanned letter needs typing first.</p>
        <input className="w-full p-2 mb-3" placeholder="Written by someone else? Their name (leave empty if you wrote it)" value={author} onChange={(e) => setAuthor(e.target.value)} />
        <input type="file" accept=".txt,.md,.docx,.pdf,.html,.htm" onChange={(e) => e.target.files?.[0] && importDoc(e.target.files[0])} />
      </section>

      <section className="surface p-6" data-testid="import-messages">
        <div className="overline mb-3">exported messages</div>
        <p className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
          A WhatsApp chat export (.txt), Facebook or Instagram messages (.json), or a CSV with sender and text columns.
          Only your own messages become memories; the other people are listed by name.
        </p>
        <input type="file" accept=".txt,.json,.csv" onChange={(e) => e.target.files?.[0] && previewChat(e.target.files[0])} />
        {preview ? (
          <div className="mt-4" data-testid="import-preview">
            <p className="text-sm mb-2">{preview.messages} messages{preview.from ? `, ${preview.from} to ${preview.to}` : ""}. Which one is you?</p>
            <select className="p-2 mb-3" value={me} onChange={(e) => setMe(e.target.value)}>
              {preview.senders.map((s) => <option key={s.name} value={s.name}>{s.name} ({s.messages})</option>)}
            </select>
            <div><button type="button" className="px-4 py-2 text-sm rounded-sm" style={primary} onClick={importChat}>Make cards from my messages</button></div>
          </div>
        ) : null}
      </section>

      {note ? <p className="text-sm">{note}</p> : null}
      {jobs.length ? (
        <section className="text-sm" data-testid="import-jobs">
          {jobs.slice(0, 6).map((j) => (
            <div key={j.import_id}>{j.name}: {j.status === "drafting" ? `${j.done} of ${j.total} cards` : j.status === "ready" ? `${j.total} cards ready to review` : "could not finish"}</div>
          ))}
        </section>
      ) : null}
    </div>
  );
}

function Review({ tick, setBusy, setError }) {
  const [cards, setCards] = useState([]);
  const [counts, setCounts] = useState({});
  const [picked, setPicked] = useState({});
  const [open, setOpen] = useState(null);
  const [version, setVersion] = useState(0);

  const load = useCallback(async () => {
    const { data } = await api.get("/life-story/cards", { params: { status: "pending" } });
    setCards(data.cards || []);
    setCounts(data.counts || {});
  }, []);

  useEffect(() => { load().catch(() => {}); }, [load, tick]);

  const ids = Object.keys(picked).filter((k) => picked[k]);
  const act = async (path, list, label, shareAll = false) => {
    if (!list.length) return;
    setBusy(label);
    setError("");
    try {
      const { data } = await api.post(`/life-story/cards/${path}`, { card_ids: list });
      if (shareAll && path === "approve" && (data?.approved || []).length) {
        // Approve and share in one go: only the cards that were actually approved.
        await api.post("/memory-loop/cards/share", { card_ids: data.approved, visibility: "family", heir_ids: [] });
      }
      setPicked({});
      setVersion((v) => v + 1);
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "That did not save.");
    } finally {
      setBusy("");
    }
  };

  const saveEdit = async () => {
    const { data } = await api.patch(`/life-story/cards/${open.card_id}`, { title: open.title, era: open.era, people: open.people, story: open.story });
    setCards((rows) => rows.map((c) => (c.card_id === open.card_id ? data.card : c)));
    setOpen(null);
  };

  return (
    <section data-testid="life-review">
      <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
        {counts.pending || 0} waiting · {counts.approved || 0} approved. Approved cards are the only memories your twin may use.
        Read each one: it should say only what really happened, in your words.
      </p>
      {cards.length ? (
        <div className="flex flex-wrap gap-3 mb-4">
          <button type="button" className="px-4 py-2 text-sm rounded-sm disabled:opacity-50" style={primary} disabled={!ids.length} onClick={() => act("approve", ids, "Approving…")} data-testid="review-approve">
            Approve {ids.length || ""} selected
          </button>
          <button type="button" className="px-4 py-2 text-sm rounded-sm disabled:opacity-50" style={{ border: "1px solid var(--accent)", color: "var(--accent)" }} disabled={!ids.length} onClick={() => act("approve", ids, "Approving and sharing…", true)} data-testid="review-approve-share">
            Approve and share with all heirs
          </button>
          <button type="button" className="px-4 py-2 text-sm rounded-sm disabled:opacity-50" style={btn} disabled={!ids.length} onClick={() => act("discard", ids, "Removing…")} data-testid="review-discard">
            Discard selected
          </button>
          <button type="button" className="px-4 py-2 text-sm rounded-sm" style={btn} onClick={() => setPicked(Object.fromEntries(cards.map((c) => [c.card_id, true])))}>
            Select all
          </button>
        </div>
      ) : (
        <p className="text-sm">Nothing waiting for review.</p>
      )}
      <div className="grid gap-3">
        {cards.map((c) => (
          <div key={c.card_id} className="surface p-4" data-testid="review-card">
            <label className="flex items-start gap-3">
              <input type="checkbox" checked={!!picked[c.card_id]} onChange={(e) => setPicked({ ...picked, [c.card_id]: e.target.checked })} className="mt-1" />
              <span className="flex-1">
                <span className="overline mr-2">{SOURCE_LABEL[c.source] || "Memory"}</span>
                <strong>{c.title}</strong>{c.era ? ` · ${c.era}` : ""}{c.people?.length ? ` · ${c.people.join(", ")}` : ""}
                <span className="block text-sm mt-1" style={{ color: "var(--text-secondary)" }}>{c.story}</span>
              </span>
              <button type="button" className="text-sm underline" onClick={() => setOpen({ ...c })}>Edit</button>
            </label>
            {open?.card_id === c.card_id ? (
              <div className="mt-3">
                <input className="w-full p-2 mb-2" value={open.title || ""} onChange={(e) => setOpen({ ...open, title: e.target.value })} aria-label="Title" />
                <input className="w-full p-2 mb-2" value={open.era || ""} placeholder="When" onChange={(e) => setOpen({ ...open, era: e.target.value })} aria-label="When" />
                <input className="w-full p-2 mb-2" value={(open.people || []).join(", ")} placeholder="People" onChange={(e) => setOpen({ ...open, people: e.target.value.split(",").map((p) => p.trim()).filter(Boolean) })} aria-label="People" />
                <textarea className="w-full min-h-[100px] p-2 mb-2" value={open.story || ""} onChange={(e) => setOpen({ ...open, story: e.target.value })} aria-label="Story" />
                <button type="button" className="px-3 py-1 text-sm rounded-sm" style={primary} onClick={saveEdit}>Save</button>
              </div>
            ) : null}
          </div>
        ))}
      </div>
      <div className="mt-10" data-testid="review-sharing">
        <HeirSharing version={version} showNames={false} />
      </div>
    </section>
  );
}

export default function LifeStory() {
  const [params] = useSearchParams();
  const [tab, setTab] = useState("interview");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const bump = useCallback(() => setTick((t) => t + 1), []);
  const tabs = [["interview", "Interview"], ["import", "Bring in memories"], ["review", "Review cards"]];

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-3xl" data-testid="life-story">
      <div className="overline mb-3">your life story</div>
      <h1 className="font-serif text-4xl font-light tracking-tight mb-3">Tell your story</h1>
      <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
        {params.get("welcome") ? "Welcome. This is the best way to teach your twin who you are. " : ""}
        Everything stays on this machine and is written by its own AI. <Link to="/today" className="underline">Do this later</Link>
      </p>
      <div className="flex gap-2 mb-6" role="tablist">
        {tabs.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className="px-3 py-1 text-sm rounded-sm" style={tab === key ? primary : btn} onClick={() => setTab(key)} data-testid={`life-tab-${key}`}>
            {label}
          </button>
        ))}
      </div>
      {tab === "interview" ? <Interview setBusy={setBusy} setError={setError} onCards={bump} /> : null}
      {tab === "import" ? <Imports setBusy={setBusy} setError={setError} onCards={bump} /> : null}
      {tab === "review" ? <Review tick={tick} setBusy={setBusy} setError={setError} /> : null}
      {busy ? <p className="mt-4 text-sm" data-testid="life-busy">{busy}</p> : null}
      {error ? <p className="mt-4 text-sm" style={{ color: "#c95a5a" }} data-testid="life-error">{error}</p> : null}
    </div>
  );
}
