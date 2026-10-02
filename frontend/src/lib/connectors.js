/** Owner mailbox connectors. Heirs never see this surface. */

export const GMAIL_ENABLED = false;

export const NOT_CONNECTED =
  "No email is connected. Connect one in Settings > Connectors.";

export const GMAIL_NOTE =
  "Gmail OAuth is not enabled. Use IMAP with an app password. A later build would need GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET plus gmail.readonly and gmail.compose. This app does not start that flow.";

export const IMAP_DEFAULTS = {
  host: "",
  port: 993,
  security: "ssl",
  smtpHost: "",
  smtpPort: 465,
  smtpSecurity: "ssl",
  username: "",
  appPassword: "",
};

const EMAIL_PRESETS = new Set(["triage_email", "summarize_thread"]);

function hostOk(value) {
  const host = String(value || "").trim();
  return Boolean(host) && !/[\s/@]/.test(host);
}

function portOk(value) {
  const port = Number(value);
  return Number.isInteger(port) && port >= 1 && port <= 65535;
}

export function validateImapForm(input) {
  const form = input || {};
  const errors = [];
  const host = String(form.host || "").trim();
  if (!hostOk(host)) errors.push("IMAP host is required.");
  if (!portOk(form.port)) errors.push("IMAP port is invalid.");
  const smtpHost = String(form.smtpHost || form.smtp_host || host).trim();
  if (!hostOk(smtpHost)) errors.push("SMTP host is required.");
  if (!portOk(form.smtpPort ?? form.smtp_port)) errors.push("SMTP port is invalid.");
  const security = String(form.security || "");
  const smtpSecurity = String(form.smtpSecurity || form.smtp_security || "");
  if (security !== "ssl" && security !== "starttls") errors.push("TLS is required.");
  if (smtpSecurity !== "ssl" && smtpSecurity !== "starttls") errors.push("SMTP TLS is required.");
  if (!String(form.username || "").trim()) errors.push("Username is required.");
  if (!String(form.appPassword || form.app_password || "").trim()) {
    errors.push("App password is required.");
  }
  return { ok: errors.length === 0, errors };
}

export function connectorNotice(preset, status) {
  const relevant = EMAIL_PRESETS.has(String(preset || ""));
  if (!relevant) return { relevant: false, connected: false, message: "" };
  if (!status) return { relevant: true, connected: false, message: "" };
  const rows = Array.isArray(status.connectors) ? status.connectors : [];
  const row = rows.find((item) => item.provider === "imap" && item.status === "connected");
  if (!row) {
    return { relevant: true, connected: false, message: NOT_CONNECTED };
  }
  const who = row.account ? ` as ${row.account}` : "";
  return {
    relevant: true,
    connected: true,
    message: `Email connected${who}. Reading and drafts stay here. Sending still needs your approval.`,
  };
}

export function imapPayload(form) {
  return {
    provider: "imap",
    host: String(form.host || "").trim(),
    port: Number(form.port),
    security: form.security,
    smtp_host: String(form.smtpHost || form.host || "").trim(),
    smtp_port: Number(form.smtpPort),
    smtp_security: form.smtpSecurity,
    username: String(form.username || "").trim(),
    app_password: String(form.appPassword || ""),
  };
}
