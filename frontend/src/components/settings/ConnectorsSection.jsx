import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "../../lib/api";
import {
  GMAIL_ENABLED,
  GMAIL_NOTE,
  IMAP_DEFAULTS,
  imapPayload,
  validateImapForm,
} from "../../lib/connectors";

const fieldStyle = {
  background: "var(--bg-base)",
  border: "1px solid var(--border-default)",
  color: "var(--text-primary)",
};

export default function ConnectorsSection() {
  const [form, setForm] = useState(IMAP_DEFAULTS);
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const { data } = await api.get("/connectors");
      setRows(data.connectors || []);
    } catch {
      setRows([]);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const set = (key) => (event) => {
    const value = event.target.type === "number" ? Number(event.target.value) : event.target.value;
    setForm((current) => ({ ...current, [key]: value }));
  };

  const imap = rows.find((row) => row.provider === "imap" && row.status === "connected");

  const testConnection = async () => {
    const checked = validateImapForm(form);
    if (!checked.ok) {
      setError(checked.errors[0]);
      return;
    }
    setBusy("test");
    setError("");
    try {
      const { data } = await api.post("/connectors/test", imapPayload(form));
      if (data.ok) toast.success(data.detail || "Signed in. Nothing was sent.");
      else setError(data.detail || "Couldn't sign in.");
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't sign in.");
    } finally {
      setBusy("");
    }
  };

  const connect = async () => {
    const checked = validateImapForm(form);
    if (!checked.ok) {
      setError(checked.errors[0]);
      return;
    }
    setBusy("connect");
    setError("");
    try {
      await api.post("/connectors/connect", imapPayload(form));
      setForm((current) => ({ ...current, appPassword: "" }));
      toast.success("Mailbox connected. Sending still needs your approval.");
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't connect.");
    } finally {
      setBusy("");
    }
  };

  const disconnect = async () => {
    setBusy("disconnect");
    setError("");
    try {
      await api.post("/connectors/disconnect", { provider: "imap" });
      toast.success("Mailbox disconnected.");
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't disconnect.");
    } finally {
      setBusy("");
    }
  };

  return (
    <section className="surface p-7 mb-6" id="connectors" data-testid="settings-connectors">
      <div className="overline mb-4">connectors</div>
      <h2 className="font-serif text-2xl mb-2">Email</h2>
      <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
        The Twin can read and draft from a mailbox you connect here. Sending always waits
        for your approval. Heirs never see this.
      </p>

      {imap ? (
        <div className="mb-5 text-sm" data-testid="connector-imap-status">
          <p style={{ color: "var(--text-primary)" }}>
            IMAP connected{imap.account ? ` as ${imap.account}` : ""}.
          </p>
          <p className="mt-1" style={{ color: "var(--text-muted)" }}>
            {(imap.scopes || []).join(" · ") || "mail.read"}
          </p>
          <button
            type="button"
            className="mt-3 text-sm"
            style={{ color: "var(--text-secondary)" }}
            onClick={disconnect}
            disabled={busy === "disconnect"}
            data-testid="connector-disconnect"
          >
            {busy === "disconnect" ? "Disconnecting…" : "Disconnect"}
          </button>
        </div>
      ) : (
        <p className="mb-5 text-sm" data-testid="connector-imap-status" style={{ color: "var(--text-muted)" }}>
          No mailbox connected.
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="IMAP host" value={form.host} onChange={set("host")} testid="connector-host" />
        <Field label="IMAP port" value={form.port} onChange={set("port")} testid="connector-port" type="number" />
        <Select label="IMAP security" value={form.security} onChange={set("security")} testid="connector-security" />
        <Field label="SMTP host" value={form.smtpHost} onChange={set("smtpHost")} testid="connector-smtp-host" />
        <Field label="SMTP port" value={form.smtpPort} onChange={set("smtpPort")} testid="connector-smtp-port" type="number" />
        <Select label="SMTP security" value={form.smtpSecurity} onChange={set("smtpSecurity")} testid="connector-smtp-security" />
        <Field label="Username" value={form.username} onChange={set("username")} testid="connector-username" />
        <Field
          label="App password"
          value={form.appPassword}
          onChange={set("appPassword")}
          testid="connector-password"
          type="password"
        />
      </div>
      {error ? (
        <p className="mt-3 text-sm" style={{ color: "var(--danger)" }} data-testid="connector-error">
          {error}
        </p>
      ) : null}
      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={testConnection}
          disabled={Boolean(busy)}
          data-testid="connector-test"
          className="px-4 py-2 text-sm rounded-sm disabled:opacity-50"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
        >
          {busy === "test" ? "Testing…" : "Test connection"}
        </button>
        <button
          type="button"
          onClick={connect}
          disabled={Boolean(busy)}
          data-testid="connector-connect"
          className="px-4 py-2 text-sm font-medium rounded-sm disabled:opacity-50"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          {busy === "connect" ? "Connecting…" : "Connect"}
        </button>
      </div>

      <div className="mt-6 pt-5" style={{ borderTop: "1px solid var(--border-default)" }} data-testid="connector-gmail">
        <p className="text-sm" style={{ color: "var(--text-primary)" }}>
          Gmail OAuth — {GMAIL_ENABLED ? "enabled" : "not enabled"}
        </p>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>
          {GMAIL_NOTE}
        </p>
      </div>
    </section>
  );
}

function Field({ label, value, onChange, testid, type = "text" }) {
  return (
    <label className="block text-sm">
      <span className="overline">{label}</span>
      <input
        className="mt-2 w-full px-3 py-2 text-sm rounded-sm"
        style={fieldStyle}
        type={type}
        value={value}
        onChange={onChange}
        data-testid={testid}
        autoComplete={type === "password" ? "new-password" : "off"}
      />
    </label>
  );
}

function Select({ label, value, onChange, testid }) {
  return (
    <label className="block text-sm">
      <span className="overline">{label}</span>
      <select
        className="mt-2 w-full px-3 py-2 text-sm rounded-sm"
        style={fieldStyle}
        value={value}
        onChange={onChange}
        data-testid={testid}
      >
        <option value="ssl">TLS (SSL)</option>
        <option value="starttls">STARTTLS</option>
      </select>
    </label>
  );
}
