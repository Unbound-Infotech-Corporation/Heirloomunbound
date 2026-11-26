import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";

export default function RecordMemory() {
  const [params] = useSearchParams();
  const [prompt, setPrompt] = useState(null);
  const [waiting, setWaiting] = useState(0);
  const [transcript, setTranscript] = useState("");
  const [card, setCard] = useState(null);
  const [ask, setAsk] = useState("");
  const [reply, setReply] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [recording, setRecording] = useState(false);
  const recorder = useRef(null);
  const chunks = useRef([]);

  const load = async () => {
    const key = params.get("key") || "";
    const topic = params.get("topic") || "";
    const cardId = params.get("card") || "";
    if (cardId) {
      const { data } = await api.get(`/memory-loop/cards/${cardId}`);
      setCard(data.card);
    }
    const { data } = await api.get("/memory-loop/next", { params: { key, question: topic } });
    setPrompt(data.prompt);
    setWaiting(data.waiting || 0);
    if (topic && !transcript) setTranscript("");
  };

  useEffect(() => {
    load().catch((err) => setError(err.response?.data?.detail || "The memory page could not load."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const saveAnswer = async () => {
    const words = transcript.trim();
    if (!words) return;
    setBusy("Saving the memory card…");
    setError("");
    try {
      const { data } = await api.post("/memory-loop/answer", {
        transcript: words,
        prompt_id: prompt?.prompt_id || "",
        key: params.get("key") || prompt?.key || "",
        question: params.get("topic") || prompt?.question || "",
      });
      setCard(data.card);
      setReply(null);
    } catch (err) {
      setError(err.response?.data?.detail || "That answer did not become a card.");
    } finally {
      setBusy("");
    }
  };

  const approve = async () => {
    if (!card?.card_id) return;
    setBusy("Saving it…");
    setError("");
    try {
      const { data } = await api.patch(`/memory-loop/cards/${card.card_id}`, {
        title: card.title,
        era: card.era,
        people: card.people,
        story: card.story,
        approve: true,
      });
      setCard(data.card);
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Could not save the card.");
    } finally {
      setBusy("");
    }
  };

  const askTwin = async () => {
    const question = ask.trim();
    if (!question) return;
    setBusy("Asking…");
    setError("");
    try {
      const { data } = await api.post("/memory-loop/ask", { question });
      setReply(data);
    } catch (err) {
      setError(err.response?.data?.detail || "The twin could not answer from approved memories.");
    } finally {
      setBusy("");
    }
  };

  const toggleRecord = async () => {
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
    media.ondataavailable = (event) => {
      if (event.data.size) chunks.current.push(event.data);
    };
    media.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop());
      const blob = new Blob(chunks.current, { type: "audio/webm" });
      const body = new FormData();
      body.append("file", blob, "memory.webm");
      setBusy("Hearing the recording…");
      try {
        const { data } = await api.post("/memory-loop/transcribe", body);
        setTranscript(data.transcript || "");
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

  const question = params.get("topic") || prompt?.question || "Tell a story you want kept.";

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-3xl" data-testid="record-memory">
      <div className="overline mb-3">one memory</div>
      <h1 className="font-serif text-4xl font-light tracking-tight mb-3">Record a memory</h1>
      <p className="text-sm mb-8" style={{ color: "var(--text-secondary)" }}>
        Answer in your words. Nothing is used until you approve the card.
        {waiting > 1 ? ` ${waiting} questions are still open. This one is for today.` : ""}
      </p>

      <section className="surface p-6 mb-6" data-testid="record-question">
        <div className="overline mb-3">the question</div>
        <p className="font-serif text-2xl leading-snug">{question}</p>
      </section>

      <label className="block mb-3 text-sm" htmlFor="memory-answer">Your answer</label>
      <textarea
        id="memory-answer"
        className="w-full min-h-[140px] p-3 text-base"
        style={{ background: "transparent", color: "var(--text-primary)", border: "1px solid var(--border-default)" }}
        value={transcript}
        onChange={(event) => setTranscript(event.target.value)}
        data-testid="record-answer"
      />
      <div className="flex flex-wrap gap-3 mt-4 mb-8">
        <button type="button" className="px-4 py-2 text-sm rounded-sm" style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }} onClick={toggleRecord} data-testid="record-voice">
          {recording ? "Stop and hear it" : "Answer by voice"}
        </button>
        <button type="button" className="px-4 py-2 text-sm rounded-sm disabled:opacity-50" style={{ background: "var(--accent)", color: "var(--text-inverse)" }} onClick={saveAnswer} disabled={!transcript.trim()} data-testid="record-save">
          Make a memory card
        </button>
      </div>

      {card ? (
        <section className="surface p-6 mb-6" data-testid="record-card">
          <div className="overline mb-3">{card.status === "approved" ? "approved" : "review this card"}</div>
          <label className="block text-sm mb-1" htmlFor="card-title">Title</label>
          <input id="card-title" className="w-full mb-3 p-2" value={card.title || ""} onChange={(event) => setCard({ ...card, title: event.target.value })} data-testid="card-title" />
          <label className="block text-sm mb-1" htmlFor="card-era">When</label>
          <input id="card-era" className="w-full mb-3 p-2" value={card.era || ""} onChange={(event) => setCard({ ...card, era: event.target.value })} data-testid="card-era" />
          <label className="block text-sm mb-1" htmlFor="card-people">People</label>
          <input
            id="card-people"
            className="w-full mb-3 p-2"
            value={(card.people || []).join(", ")}
            onChange={(event) => setCard({ ...card, people: event.target.value.split(",").map((part) => part.trim()).filter(Boolean) })}
            data-testid="card-people"
          />
          <label className="block text-sm mb-1" htmlFor="card-story">In your words</label>
          <textarea id="card-story" className="w-full min-h-[120px] p-2 mb-3" value={card.story || ""} onChange={(event) => setCard({ ...card, story: event.target.value })} data-testid="card-story" />
          <p className="text-xs mb-4" style={{ color: "var(--text-muted)" }} data-testid="card-transcript">Source: {card.transcript}</p>
          {card.status !== "approved" ? (
            <button type="button" className="px-4 py-2 text-sm rounded-sm" style={{ background: "var(--accent)", color: "var(--text-inverse)" }} onClick={approve} data-testid="card-approve">Approve</button>
          ) : (
            <p className="text-sm" data-testid="card-approved">Approved. The twin can use this memory.</p>
          )}
        </section>
      ) : null}

      <section className="surface p-6" data-testid="record-ask">
        <div className="overline mb-3">ask from approved memories</div>
        <div className="flex gap-3">
          <input className="flex-1 p-2" value={ask} onChange={(event) => setAsk(event.target.value)} placeholder="What did they teach you?" data-testid="record-ask-input" />
          <button type="button" className="px-4 py-2 text-sm rounded-sm" style={{ border: "1px solid var(--border-default)" }} onClick={askTwin} data-testid="record-ask-send">Ask</button>
        </div>
        {reply ? (
          <div className="mt-4">
            <p className="font-serif text-xl" data-testid="record-reply">{reply.reply}</p>
            {reply.why?.length ? (
              <div className="mt-3" data-testid="record-why">
                <div className="overline mb-2">Why did I say that?</div>
                {reply.why.map((item) => (
                  <Link key={item.card_id} to={`/record?card=${item.card_id}`} className="block text-sm">
                    {item.title}
                  </Link>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      {busy ? <p className="mt-4 text-sm" data-testid="record-busy">{busy}</p> : null}
      {error ? <p className="mt-4 text-sm" data-testid="record-error" style={{ color: "#c95a5a" }}>{error}</p> : null}
    </div>
  );
}
