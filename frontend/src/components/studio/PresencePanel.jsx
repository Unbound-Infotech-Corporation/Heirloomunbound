import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { cameraSummary, consentText, presentLabel, samplesStillNeeded } from "../../lib/presence";

const EMPTY_FORM = {
  name: "",
  relationship: "owner",
  greeting: "",
  consent: false,
};

function readJpeg(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read that photo"));
    reader.readAsDataURL(file);
  });
}

export default function PresencePanel({ showIntro = false }) {
  const [status, setStatus] = useState(null);
  const [people, setPeople] = useState([]);
  const [events, setEvents] = useState([]);
  const [unknown, setUnknown] = useState([]);
  const [closed, setClosed] = useState(false);
  const [off, setOff] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [form, setForm] = useState(EMPTY_FORM);
  const [threshold, setThreshold] = useState("0.36");
  const [debounce, setDebounce] = useState("10");
  const [quiet, setQuiet] = useState("");
  const [unknownThumbs, setUnknownThumbs] = useState(false);
  const [testResult, setTestResult] = useState("");
  const [forgetArmed, setForgetArmed] = useState(false);

  const load = useCallback(() => {
    api.get("/presence/status")
      .then(({ data }) => {
        setStatus(data);
        if (!data?.enabled) {
          setOff(true);
          setClosed(false);
          return null;
        }
        setOff(false);
        setClosed(false);
        setThreshold(String(data.threshold ?? 0.36));
        setDebounce(String(data.debounce_minutes ?? 10));
        setQuiet(data.quiet_hours || "");
        setUnknownThumbs(Boolean(data.unknown_thumbnails));
        return Promise.all([
          api.get("/presence/people"),
          api.get("/presence/events"),
          api.get("/presence/unknown"),
        ]);
      })
      .then((bundle) => {
        if (!bundle) return;
        const [peopleRes, eventsRes, unknownRes] = bundle;
        setPeople(peopleRes.data.people || []);
        setEvents(eventsRes.data.events || []);
        setUnknown(unknownRes.data.unknown || []);
      })
      .catch(() => setClosed(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const fail = (err) => {
    const detail = err?.response?.data?.detail;
    setError(typeof detail === "string" ? detail : "That did not save.");
  };

  const setPaused = (paused) => {
    setBusy(paused ? "pause" : "resume");
    setError("");
    api.post(paused ? "/presence/pause" : "/presence/resume")
      .then(() => load())
      .catch(fail)
      .finally(() => setBusy(""));
  };

  const teach = (event) => {
    event.preventDefault();
    setBusy("teach");
    setError("");
    api.post("/presence/people", form)
      .then(() => {
        setForm(EMPTY_FORM);
        load();
      })
      .catch(fail)
      .finally(() => setBusy(""));
  };

  const pollJob = (jobId) => {
    const started = Date.now();
    const tick = () => {
      api.get(`/presence/jobs/${jobId}`)
        .then(({ data }) => {
          const job = data.job || {};
          if (job.status === "pending" && Date.now() - started < 20000) {
            window.setTimeout(tick, 700);
            return;
          }
          if (job.status === "failed") setError(job.error || "The camera did not see a face.");
          if (job.result && Object.prototype.hasOwnProperty.call(job.result, "matched")) {
            setTestResult(job.result.matched
              ? `${job.result.name} · ${Number(job.result.score || 0).toFixed(2)} · nothing stored`
              : "Unrecognized. Nothing was stored.");
          }
          load();
        })
        .catch(fail);
    };
    tick();
  };

  const capture = (personId) => {
    setBusy(personId);
    setError("");
    api.post(`/presence/people/${personId}/capture`)
      .then(({ data }) => pollJob(data.job.id))
      .catch(fail)
      .finally(() => setBusy(""));
  };

  const upload = async (personId, file) => {
    if (!file) return;
    setBusy(personId);
    setError("");
    try {
      const image_base64 = await readJpeg(file);
      const { data } = await api.post(`/presence/people/${personId}/samples`, { image_base64 });
      if (data.job?.id) pollJob(data.job.id);
      else load();
    } catch (err) {
      fail(err);
    } finally {
      setBusy("");
    }
  };

  const savePerson = (person, patch) => {
    setBusy(person.id);
    setError("");
    api.patch(`/presence/people/${person.id}`, patch)
      .then(() => load())
      .catch(fail)
      .finally(() => setBusy(""));
  };

  const removePerson = (personId) => {
    setBusy(personId);
    setError("");
    api.delete(`/presence/people/${personId}`)
      .then(() => load())
      .catch(fail)
      .finally(() => setBusy(""));
  };

  const saveSettings = (event) => {
    event.preventDefault();
    setBusy("settings");
    setError("");
    api.put("/presence/settings", {
      threshold: Number(threshold),
      debounce_minutes: Number(debounce),
      quiet_hours: quiet,
      unknown_thumbnails: unknownThumbs,
    })
      .then(() => load())
      .catch(fail)
      .finally(() => setBusy(""));
  };

  const testLive = () => {
    setBusy("test");
    setError("");
    setTestResult("");
    api.post("/presence/test", { live: true })
      .then(({ data }) => pollJob(data.job.id))
      .catch(fail)
      .finally(() => setBusy(""));
  };

  const forget = () => {
    setBusy("forget");
    setError("");
    api.post("/presence/forget")
      .then(() => {
        setForgetArmed(false);
        load();
      })
      .catch(fail)
      .finally(() => setBusy(""));
  };

  if (closed) {
    return (
      <p className="text-sm" data-testid="presence-closed" style={{ color: "var(--text-muted)" }}>
        Presence is not available.
      </p>
    );
  }

  if (off) {
    return (
      <p className="text-sm" data-testid="presence-off" style={{ color: "var(--text-muted)" }}>
        Presence is off on this server.
      </p>
    );
  }

  return (
    <div data-testid="presence-panel">
      {showIntro ? (
        <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
          The box recognizes people you teach and keeps an embedding plus a thumbnail.
          It does not keep video, and it does not enroll a stranger.
        </p>
      ) : null}

      <section className="surface p-5 mb-6" data-testid="presence-status">
        <div className="overline mb-2">room</div>
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
          {status
            ? `${cameraSummary(status.cameras, status.fps)} · ${status.enrolled || 0} enrolled · ${status.paused ? "paused" : "watching"}`
            : "Checking…"}
        </p>
        <p className="text-sm mt-2" data-testid="presence-who" style={{ color: "var(--text-primary)" }}>
          {presentLabel(status?.present)}
        </p>
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            className="text-sm px-3 py-1.5 rounded-sm"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            data-testid="presence-pause"
            disabled={busy === "pause" || status?.paused}
            onClick={() => setPaused(true)}
          >
            Pause
          </button>
          <button
            type="button"
            className="text-sm px-3 py-1.5 rounded-sm"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            data-testid="presence-resume"
            disabled={busy === "resume" || !status?.paused}
            onClick={() => setPaused(false)}
          >
            Resume
          </button>
        </div>
      </section>

      <section className="surface p-5 mb-6" data-testid="presence-teach">
        <div className="overline mb-2">Teach a person</div>
        <form onSubmit={teach} className="space-y-3">
          <label className="block text-sm" style={{ color: "var(--text-secondary)" }}>
            Name
            <input
              className="mt-1 w-full px-3 py-2 text-sm"
              style={{ background: "transparent", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              data-testid="presence-name"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              required
            />
          </label>
          <label className="block text-sm" style={{ color: "var(--text-secondary)" }}>
            Relationship
            <input
              className="mt-1 w-full px-3 py-2 text-sm"
              style={{ background: "transparent", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              data-testid="presence-relationship"
              value={form.relationship}
              onChange={(event) => setForm({ ...form, relationship: event.target.value })}
              required
            />
          </label>
          <label className="block text-sm" style={{ color: "var(--text-secondary)" }}>
            Greeting
            <input
              className="mt-1 w-full px-3 py-2 text-sm"
              style={{ background: "transparent", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              data-testid="presence-greeting"
              placeholder="Welcome back."
              value={form.greeting}
              onChange={(event) => setForm({ ...form, greeting: event.target.value })}
            />
          </label>
          <label className="flex items-start gap-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            <input
              type="checkbox"
              data-testid="presence-consent"
              checked={form.consent}
              onChange={(event) => setForm({ ...form, consent: event.target.checked })}
              required
            />
            <span>{consentText()}</span>
          </label>
          <button
            type="submit"
            className="text-sm px-3 py-1.5 rounded-sm"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            data-testid="presence-teach-submit"
            disabled={busy === "teach" || !form.consent}
          >
            Save person
          </button>
        </form>
      </section>

      <section className="surface p-5 mb-6" data-testid="presence-people">
        <div className="overline mb-2">People</div>
        {people.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>Nobody taught yet.</p>
        ) : (
          <ul className="space-y-4">
            {people.map((person) => (
              <li key={person.id} data-testid={`presence-person-${person.id}`}>
                <p className="text-sm" style={{ color: "var(--text-primary)" }}>
                  {person.name} · {person.relationship} · {person.sample_count} samples
                  {samplesStillNeeded(person.sample_count) > 0
                    ? ` · ${samplesStillNeeded(person.sample_count)} more helps`
                    : ""}
                </p>
                <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                  {person.greeting || "Welcome back."}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="text-xs px-2 py-1 rounded-sm"
                    style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                    data-testid={`presence-capture-${person.id}`}
                    disabled={busy === person.id}
                    onClick={() => capture(person.id)}
                  >
                    Capture sample
                  </button>
                  <label className="text-xs px-2 py-1 rounded-sm" style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}>
                    Upload JPEG
                    <input
                      type="file"
                      accept="image/jpeg"
                      className="sr-only"
                      data-testid={`presence-upload-${person.id}`}
                      onChange={(event) => upload(person.id, event.target.files && event.target.files[0])}
                    />
                  </label>
                  <button
                    type="button"
                    className="text-xs px-2 py-1 rounded-sm"
                    style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                    data-testid={`presence-rename-${person.id}`}
                    onClick={() => {
                      const name = window.prompt("Name", person.name);
                      if (name && name !== person.name) savePerson(person, { name });
                    }}
                  >
                    Rename
                  </button>
                  <button
                    type="button"
                    className="text-xs px-2 py-1 rounded-sm"
                    style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                    data-testid={`presence-delete-${person.id}`}
                    onClick={() => removePerson(person.id)}
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="surface p-5 mb-6" data-testid="presence-test">
        <div className="overline mb-2">Test recognition</div>
        <p className="text-sm mb-3" style={{ color: "var(--text-muted)" }}>
          One look from the camera. A miss is not enrolled.
        </p>
        <button
          type="button"
          className="text-sm px-3 py-1.5 rounded-sm"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          data-testid="presence-test-live"
          disabled={busy === "test"}
          onClick={testLive}
        >
          Look once
        </button>
        {testResult ? (
          <p className="text-sm mt-3" data-testid="presence-test-result" style={{ color: "var(--text-primary)" }}>
            {testResult}
          </p>
        ) : null}
      </section>

      <form className="surface p-5 mb-6" data-testid="presence-settings" onSubmit={saveSettings}>
        <div className="overline mb-2">Threshold and quiet hours</div>
        <label className="block text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
          Match threshold (0.05–0.95)
          <input
            className="mt-1 w-full px-3 py-2 text-sm"
            style={{ background: "transparent", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            data-testid="presence-threshold"
            value={threshold}
            onChange={(event) => setThreshold(event.target.value)}
          />
        </label>
        <label className="block text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
          Do not greet again for (minutes)
          <input
            className="mt-1 w-full px-3 py-2 text-sm"
            style={{ background: "transparent", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            data-testid="presence-debounce"
            value={debounce}
            onChange={(event) => setDebounce(event.target.value)}
          />
        </label>
        <label className="block text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
          Quiet hours
          <input
            className="mt-1 w-full px-3 py-2 text-sm"
            style={{ background: "transparent", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            data-testid="presence-quiet"
            placeholder="23:00-07:00"
            value={quiet}
            onChange={(event) => setQuiet(event.target.value)}
          />
        </label>
        <label className="flex items-start gap-2 text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
          <input
            type="checkbox"
            data-testid="presence-unknown-thumbs"
            checked={unknownThumbs}
            onChange={(event) => setUnknownThumbs(event.target.checked)}
          />
          <span>Keep one thumbnail of an unrecognized face for 24 hours. Off by default.</span>
        </label>
        <button
          type="submit"
          className="text-sm px-3 py-1.5 rounded-sm"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          data-testid="presence-settings-save"
          disabled={busy === "settings"}
        >
          Save settings
        </button>
      </form>

      <section className="surface p-5 mb-6" data-testid="presence-events">
        <div className="overline mb-2">Arrivals</div>
        {events.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>No events yet.</p>
        ) : (
          <ul className="space-y-2">
            {events.slice().reverse().map((event, index) => (
              <li key={`${event.ts}-${event.kind}-${index}`} className="text-sm" style={{ color: "var(--text-secondary)" }}>
                {event.kind === "unrecognized"
                  ? `${event.ts} · unrecognized person`
                  : `${event.ts} · ${event.kind}${event.name ? ` · ${event.name}` : ""}${event.greeted ? " · greeted" : ""}`}
              </li>
            ))}
          </ul>
        )}
        {unknown.length > 0 ? (
          <p className="text-xs mt-3" data-testid="presence-unknown-count" style={{ color: "var(--text-muted)" }}>
            {unknown.length} unrecognized thumbnail{unknown.length === 1 ? "" : "s"} waiting to expire.
          </p>
        ) : null}
      </section>

      {error ? (
        <p className="text-sm mb-4" data-testid="presence-error" style={{ color: "var(--text-primary)" }}>{error}</p>
      ) : null}

      <section className="surface p-5" data-testid="presence-forget">
        <div className="overline mb-2">Forget everyone</div>
        <p className="text-sm mb-3" style={{ color: "var(--text-muted)" }}>
          Deletes every embedding and thumbnail on this box.
        </p>
        <label className="flex items-start gap-2 text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
          <input
            type="checkbox"
            data-testid="presence-forget-arm"
            checked={forgetArmed}
            onChange={(event) => setForgetArmed(event.target.checked)}
          />
          <span>I want these faces removed.</span>
        </label>
        <button
          type="button"
          className="text-sm px-3 py-1.5 rounded-sm"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          data-testid="presence-forget-button"
          disabled={!forgetArmed || busy === "forget"}
          onClick={forget}
        >
          Forget everyone
        </button>
      </section>
    </div>
  );
}
