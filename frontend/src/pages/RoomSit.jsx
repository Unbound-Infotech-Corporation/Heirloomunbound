import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Loader2 } from "lucide-react";
import RoomViewer3D, { tryEnterWebXR } from "../components/studio/RoomViewer3D";
import AssistantPicker from "../components/studio/AssistantPicker";
import { api, streamSSE } from "../lib/api";
import { speakerLabel } from "../lib/assistants";

export default function RoomSit() {
  const { roomId } = useParams();
  const [room, setRoom] = useState(null);
  const [gltf, setGltf] = useState(null);
  const [error, setError] = useState("");
  const [xrNote, setXrNote] = useState("");
  const [assistants, setAssistants] = useState([]);
  const [selectedAssistant, setSelectedAssistant] = useState(null);
  const [conv, setConv] = useState(null);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [streaming, setStreaming] = useState("");
  const canvasWrap = useRef(null);

  useEffect(() => {
    api.get(`/rooms/${roomId}`).then(({ data }) => setRoom(data)).catch(() => setError("Room not found."));
    api.get(`/rooms/${roomId}/scene`).then(({ data }) => setGltf(data)).catch(() => setGltf(null));
    api.get("/clones").then(({ data }) => setAssistants(data.clones || [])).catch(() => {});
    api.post("/twin/start", {}).then(({ data }) => setConv(data)).catch(() => {});
  }, [roomId]);

  const send = async (text) => {
    if (!text.trim() || !conv || pending) return;
    const myMsg = { role: "user", content: text, ts: new Date().toISOString() };
    setConv((c) => ({ ...c, messages: [...(c.messages || []), myMsg] }));
    setInput("");
    setPending(true);
    setStreaming("");
    let full = "";
    let specialistName = "";
    await streamSSE(
      "/twin/message",
      {
        conversation_id: conv.conversation_id,
        message: text,
        clone_id: selectedAssistant || undefined,
        room_id: roomId,
      },
      (chunk) => {
        full += chunk;
        setStreaming(full);
      },
      () => {
        setConv((c) => ({
          ...c,
          messages: [
            ...c.messages,
            {
              role: "assistant",
              content: full,
              ts: new Date().toISOString(),
              specialist_name: specialistName || undefined,
              specialist_id: selectedAssistant || undefined,
            },
          ],
        }));
        setStreaming("");
        setPending(false);
      },
      () => {
        setStreaming("");
        setPending(false);
      },
      (eventName, data) => {
        if (eventName === "specialist" && data?.name) specialistName = data.name;
      },
    );
  };

  const messages = conv?.messages || [];

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-8 max-w-6xl" data-testid="room-sit">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 text-xs" style={{ color: "var(--text-muted)" }}>
        <Link to={`/rooms/${roomId}`} className="hover:text-[var(--accent)]" data-testid="room-sit-back">
          ← {room?.name || "room"}
        </Link>
        <Link to={`/twin?room=${encodeURIComponent(roomId)}`} className="hover:text-[var(--accent)]" data-testid="room-sit-twin">
          Open full Twin sitting →
        </Link>
      </div>

      <div className="grid lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3 surface overflow-hidden" style={{ minHeight: 360 }}>
          <div ref={canvasWrap} className="h-[52vh] min-h-[320px]" data-testid="room-sit-stage">
            {gltf ? (
              <RoomViewer3D gltf={gltf} title={room?.name} />
            ) : (
              <div className="h-full flex items-center justify-center text-sm" style={{ color: "var(--text-muted)" }}>
                {error || "Loading the stand-in scene…"}
              </div>
            )}
          </div>
          <div className="px-4 py-3 flex justify-between items-center" style={{ borderTop: "1px solid var(--border-default)" }}>
            <span className="overline">placeholder glTF · mock reconstruct</span>
            <button
              type="button"
              data-testid="room-sit-xr"
              onClick={async () => {
                const canvas = canvasWrap.current?.querySelector("canvas");
                const result = await tryEnterWebXR(canvas);
                setXrNote(result.ok ? "WebXR session started." : result.reason);
                if (result.session) {
                  result.session.addEventListener("end", () => setXrNote(""));
                }
              }}
              className="text-xs px-3 py-1 rounded-sm"
              style={{ border: "1px solid var(--border-default)" }}
            >
              Enter VR
            </button>
          </div>
          {xrNote ? (
            <p className="px-4 pb-3 text-xs" style={{ color: "var(--text-muted)" }} data-testid="room-sit-xr-note">
              {xrNote}
            </p>
          ) : null}
        </div>

        <div className="lg:col-span-2 surface p-4 flex flex-col" style={{ minHeight: 360 }} data-testid="room-sit-chat">
          <div className="overline mb-2">twin in this place</div>
          <AssistantPicker
            clones={assistants}
            selectedId={selectedAssistant}
            onSelect={setSelectedAssistant}
            testid="room-sit-clones"
          />
          <div className="flex-1 overflow-y-auto mt-4 space-y-4 max-h-[40vh]" data-testid="room-sit-feed">
            {messages.map((m, i) => (
              <div key={`${m.ts}-${i}`}>
                <div className="overline mb-1">
                  {m.role === "assistant" ? speakerLabel(m, assistants) : "you"}
                </div>
                <p className="text-sm leading-relaxed" style={{ color: "var(--text-primary)" }}>
                  {m.content}
                </p>
              </div>
            ))}
            {streaming ? (
              <p className="font-serif text-lg" style={{ color: "var(--text-primary)" }}>{streaming}</p>
            ) : null}
          </div>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={3}
            placeholder="Talk here. @Research or pick a clone."
            data-testid="room-sit-input"
            className="mt-3 w-full bg-transparent outline-none resize-none text-sm"
            style={{ color: "var(--text-primary)" }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                send(input);
              }
            }}
          />
          <button
            type="button"
            onClick={() => send(input)}
            disabled={pending || !input.trim()}
            data-testid="room-sit-send"
            className="mt-2 inline-flex items-center justify-center gap-2 px-4 py-2 text-sm rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
