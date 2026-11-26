// Talks only to the buyer's own box. No other server, no cloud model.
export type Session = { box: string; token: string; deviceId: string; name: string; pin: string };
export type Reply = { reply: string; userText?: string };
type Fetch = typeof fetch;

export class BoxError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') return body.detail;
  } catch {
    // not json
  }
  return `The box answered ${res.status}.`;
}

export async function claim(
  box: string, code: string, platform: 'android' | 'ios', deviceName: string, pin = '', f: Fetch = fetch,
): Promise<Session> {
  const res = await f(`${box}/api/mobile/pair/claim`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, platform, device_name: deviceName }),
  });
  if (!res.ok) throw new BoxError(res.status, await detail(res));
  const body = await res.json();
  return { box, token: body.device_token, deviceId: body.device_id, name: body.name, pin };
}

export class BoxClient {
  constructor(private session: Session, private f: Fetch = fetch) {}

  get headers(): Record<string, string> {
    return { Authorization: `Bearer ${this.session.token}` };
  }

  private async call(path: string, init: RequestInit = {}): Promise<any> {
    const res = await this.f(`${this.session.box}/api${path}`, {
      ...init,
      headers: { ...(init.headers as Record<string, string>), ...this.headers },
    });
    if (!res.ok) throw new BoxError(res.status, await detail(res));
    return res.json();
  }

  me(): Promise<{ device_id: string; owner: string; voice: boolean; local_only: boolean }> {
    return this.call('/mobile/me');
  }

  async chat(text: string, mode: 'twin' | 'assistant' = 'twin'): Promise<Reply> {
    const body = await this.call('/desktop/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, mode }),
    });
    return { reply: body.reply || '' };
  }

  /** Recorded audio -> the box's local Whisper -> the Twin. */
  async voice(fileUri: string, mime = 'audio/m4a'): Promise<Reply> {
    const form = new FormData();
    const name = fileUri.split('/').pop() || 'talk.m4a';
    form.append('audio', { uri: fileUri, name, type: mime } as unknown as Blob);
    form.append('audience', 'owner');
    const body = await this.call('/companion/voice', { method: 'POST', body: form });
    return { reply: body.reply || '', userText: body.user_text || '' };
  }

  /** A GET the audio player can stream with our Bearer header; the box's local voice renders it. */
  speakSource(text: string): { uri: string; headers: Record<string, string> } {
    return { uri: `${this.session.box}/api/mobile/speak.wav?text=${encodeURIComponent(text.slice(0, 1200))}`, headers: this.headers };
  }
}
