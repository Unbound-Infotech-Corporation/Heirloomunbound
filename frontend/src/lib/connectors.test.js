import {
  GMAIL_ENABLED,
  GMAIL_NOTE,
  IMAP_DEFAULTS,
  NOT_CONNECTED,
  connectorNotice,
  imapPayload,
  validateImapForm,
} from "./connectors";

const valid = {
  ...IMAP_DEFAULTS,
  host: "imap.example.com",
  smtpHost: "smtp.example.com",
  username: "owner@example.com",
  appPassword: "app-password",
};

describe("imap form", () => {
  test("requires tls, host, and an app password", () => {
    expect(validateImapForm(valid).ok).toBe(true);
    expect(validateImapForm({ ...valid, security: "none" }).errors).toContain("TLS is required.");
    expect(validateImapForm({ ...valid, smtpSecurity: "plain" }).errors).toContain(
      "SMTP TLS is required.",
    );
    expect(validateImapForm({ ...valid, host: "" }).ok).toBe(false);
    expect(validateImapForm({ ...valid, appPassword: "" }).errors).toContain(
      "App password is required.",
    );
    expect(validateImapForm({ ...valid, port: 0 }).ok).toBe(false);
  });

  test("payload uses the app password field and does not invent gmail", () => {
    const payload = imapPayload(valid);
    expect(payload.provider).toBe("imap");
    expect(payload.app_password).toBe("app-password");
    expect(payload.security).toBe("ssl");
    expect(payload.port).toBe(993);
    expect(GMAIL_ENABLED).toBe(false);
    expect(GMAIL_NOTE).toMatch(/not enabled/i);
  });
});

describe("assignment connector notice", () => {
  test("blank presets ignore the mailbox", () => {
    expect(connectorNotice("blank", { connectors: [] }).relevant).toBe(false);
  });

  test("email presets say when nothing is connected", () => {
    expect(connectorNotice("triage_email", { connectors: [] }).message).toBe(NOT_CONNECTED);
    expect(connectorNotice("summarize_thread", null).message).toBe("");
  });

  test("a connected imap row names the account and still requires approval", () => {
    const notice = connectorNotice("triage_email", {
      connectors: [{ provider: "imap", status: "connected", account: "owner@example.com" }],
    });
    expect(notice.connected).toBe(true);
    expect(notice.message).toMatch(/owner@example.com/);
    expect(notice.message).toMatch(/approval/i);
  });
});
