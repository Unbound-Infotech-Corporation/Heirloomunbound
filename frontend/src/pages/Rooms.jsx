import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Box, Headset, Loader2, Upload } from "lucide-react";
import { api } from "../lib/api";
import { CAPTURE_HINTS, canEnterRoom, roomStatusLabel } from "../lib/rooms";
import { VR_MATRIX_PATH, VR_SETUP_PATH } from "../lib/vrCompat";

export default function Rooms() {
  const [rooms, setRooms] = useState([]);
  const [instructions, setInstructions] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const load = async () => {
    const { data } = await api.get("/rooms");
    setRooms(data.rooms || []);
    setInstructions(data.capture_instructions || "");
  };

  useEffect(() => {
    load().catch(() => setError("Couldn't load rooms."));
  }, []);

  const create = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const { data } = await api.post("/rooms", { name: name.trim() });
      setName("");
      await load();
      navigate(`/rooms/${data.room_id}`);
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't create the room.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-4xl" data-testid="rooms-root">
      <header className="mb-10">
        <div className="overline mb-3">heirloom room</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
          Capture a place. Sit there later.
        </h1>
        <p className="mt-3 text-base max-w-xl" style={{ color: "var(--text-secondary)" }}>
          Film a real room. Phase 1 builds a stand-in scene you can enter in the browser
          and talk with your twin inside it. Headset sit uses OpenXR on the PC (via WebXR)
          or the Quest browser.
        </p>
        <p className="mt-4 flex flex-wrap gap-4 text-sm">
          <Link to={VR_SETUP_PATH} data-testid="rooms-vr-setup" className="inline-flex items-center gap-1.5" style={{ color: "var(--accent)" }}>
            <Headset className="h-4 w-4" /> VR setup coach
          </Link>
          <Link to={VR_MATRIX_PATH} data-testid="rooms-vr-matrix" style={{ color: "var(--accent)" }}>
            Headset matrix
          </Link>
        </p>
      </header>

      <section className="surface p-6 mb-10" data-testid="rooms-capture-help">
        <div className="overline mb-3">how to film</div>
        <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
          {instructions || CAPTURE_HINTS[0]}
        </p>
        <ul className="space-y-2 text-sm" style={{ color: "var(--text-muted)" }}>
          {CAPTURE_HINTS.map((hint) => (
            <li key={hint}>· {hint}</li>
          ))}
        </ul>
      </section>

      <section className="surface p-6 mb-10" data-testid="rooms-create">
        <div className="overline mb-3">new room</div>
        <div className="flex flex-col sm:flex-row gap-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="The living room, the kitchen…"
            data-testid="rooms-new-name"
            className="flex-1 px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            onKeyDown={(e) => {
              if (e.key === "Enter") create();
            }}
          />
          <button
            type="button"
            onClick={create}
            disabled={busy || !name.trim()}
            data-testid="rooms-create-btn"
            className="inline-flex items-center justify-center gap-2 px-5 py-2 text-sm rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Box className="h-4 w-4" />}
            Create room
          </button>
        </div>
        {error ? (
          <p className="text-sm mt-3" style={{ color: "#c95a5a" }} data-testid="rooms-error">
            {error}
          </p>
        ) : null}
      </section>

      <section data-testid="rooms-list">
        {rooms.length === 0 ? (
          <div className="surface p-8" data-testid="rooms-empty">
            <div className="overline mb-2">none yet</div>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              Name a room, upload a video or a set of stills, then build the stand-in scene.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {rooms.map((room) => (
              <Link
                key={room.room_id}
                to={`/rooms/${room.room_id}`}
                data-testid={`room-card-${room.room_id}`}
                className="surface p-5 flex items-center justify-between gap-4 hover:opacity-90"
              >
                <div>
                  <div className="font-serif text-xl">{room.name}</div>
                  <div className="overline mt-1">{roomStatusLabel(room.capture_status)}</div>
                </div>
                <span className="inline-flex items-center gap-1 text-xs" style={{ color: "var(--accent)" }}>
                  {canEnterRoom(room) ? "sit here" : "open"} <ArrowRight className="h-3.5 w-3.5" />
                </span>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export function RoomDetail() {
  const { roomId } = useParams();
  return <RoomEditor roomId={roomId} />;
}

export function RoomEditor({ roomId }) {
  const [room, setRoom] = useState(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef(null);
  const navigate = useNavigate();

  const load = async () => {
    const { data } = await api.get(`/rooms/${roomId}`);
    setRoom(data);
  };

  useEffect(() => {
    load().catch(() => setError("Couldn't load this room."));
  }, [roomId]);

  const onFiles = async (list) => {
    const files = Array.from(list || []);
    if (!files.length) return;
    setUploading(true);
    setError("");
    try {
      for (const file of files) {
        const fd = new FormData();
        fd.append("file", file);
        await api.post(`/rooms/${roomId}/assets`, fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      }
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const reconstruct = async () => {
    setBusy(true);
    setError("");
    try {
      const { data } = await api.post(`/rooms/${roomId}/reconstruct`, { backend: "mock" });
      setRoom(data);
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't build the stand-in scene.");
    } finally {
      setBusy(false);
    }
  };

  if (!room) {
    return (
      <div className="px-4 sm:px-8 lg:px-16 py-12" data-testid="room-detail-loading">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  const assets = room.assets || [];

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-4xl" data-testid="room-detail">
      <div className="mb-8 text-xs" style={{ color: "var(--text-muted)" }}>
        <Link to="/rooms" className="hover:text-[var(--accent)]" data-testid="room-back">
          ← all rooms
        </Link>
      </div>
      <header className="mb-8">
        <div className="overline mb-3">heirloom room</div>
        <h1 className="font-serif text-4xl font-light tracking-tight">{room.name}</h1>
        <p className="mt-2 overline">{roomStatusLabel(room.capture_status)}</p>
      </header>

      <section className="surface p-6 mb-6" data-testid="room-upload">
        <div className="overline mb-3">capture</div>
        <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
          {room.capture_instructions}
        </p>
        <input
          ref={fileRef}
          type="file"
          accept="image/*,video/mp4,video/webm,video/quicktime"
          multiple
          hidden
          onChange={(e) => onFiles(e.target.files)}
          data-testid="room-file-input"
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          data-testid="room-upload-btn"
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded-sm disabled:opacity-50"
          style={{ border: "1px solid var(--border-default)" }}
        >
          {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          Upload video or stills
        </button>
        <ul className="mt-4 space-y-1 text-xs" style={{ color: "var(--text-muted)" }} data-testid="room-assets">
          {assets.map((a) => (
            <li key={a.asset_id}>
              {a.kind} · {a.original_filename || a.asset_id} · {Math.round((a.size || 0) / 1024)} KB
              {a.stored ? "" : " · metadata only"}
            </li>
          ))}
          {assets.length === 0 ? <li>No files yet.</li> : null}
        </ul>
      </section>

      <section className="surface p-6 mb-6" data-testid="room-reconstruct">
        <div className="overline mb-3">reconstruction</div>
        <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
          Phase 1 uses a mock path: it marks the room ready and attaches a placeholder glTF
          volume. No paid photogrammetry or splat vendor is called.
        </p>
        <button
          type="button"
          onClick={reconstruct}
          disabled={busy}
          data-testid="room-reconstruct-btn"
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded-sm disabled:opacity-50"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Box className="h-4 w-4" />}
          Build stand-in scene
        </button>
      </section>

      {error ? (
        <p className="text-sm mb-4" style={{ color: "#c95a5a" }} data-testid="room-error">
          {error}
        </p>
      ) : null}

      {canEnterRoom(room) ? (
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => navigate(`/rooms/${room.room_id}/sit`)}
            data-testid="room-enter-btn"
            className="inline-flex items-center gap-2 px-5 py-2 text-sm rounded-sm"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            Sit in this room <ArrowRight className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => navigate(`${VR_SETUP_PATH}`)}
            data-testid="room-xr-note-btn"
            className="px-4 py-2 text-sm rounded-sm inline-flex items-center gap-2"
            style={{ border: "1px solid var(--border-default)" }}
          >
            <Headset className="h-4 w-4" /> VR setup coach
          </button>
        </div>
      ) : null}
    </div>
  );
}
