// Mirrors backend/mobile_pairing.py: the QR the box shows, and the typed code.
export const ALPHABET = 'ABCDEFGHJKMNPQRSTVWXYZ23456789';
export const CODE_LEN = 8;
export const SCHEME = 'heirloom://pair';

export type Pairing = { box: string; code: string; pin: string };

export function normalizeCode(raw: string): string {
  return (raw || '').replace(/[^0-9a-z]/gi, '').toUpperCase();
}

export function displayCode(code: string): string {
  const c = normalizeCode(code);
  return c.length > 4 ? `${c.slice(0, 4)}-${c.slice(4)}` : c;
}

export function normalizeBoxUrl(raw: string): string {
  let url = (raw || '').trim().replace(/\/+$/, '');
  if (url && !/^https?:\/\//i.test(url)) url = `https://${url}`;
  return url;
}

/** heirloom://pair?box=...&code=...&pin=... -> fields, or null if it is not a Heirloom pairing QR. */
export function parseQr(text: string): Pairing | null {
  const raw = (text || '').trim();
  if (!raw.startsWith(SCHEME)) return null;
  const q = raw.indexOf('?');
  if (q < 0) return null;
  const params: Record<string, string> = {};
  for (const part of raw.slice(q + 1).split('&')) {
    if (!part) continue;
    const eq = part.indexOf('=');
    const key = decodeURIComponent((eq < 0 ? part : part.slice(0, eq)).replace(/\+/g, ' '));
    const value = eq < 0 ? '' : decodeURIComponent(part.slice(eq + 1).replace(/\+/g, ' '));
    if (!(key in params)) params[key] = value;
  }
  const box = params.box || '';
  const code = params.code || '';
  if (!/^https?:\/\//.test(box) || code.length !== CODE_LEN) return null;
  return { box: box.replace(/\/+$/, ''), code, pin: params.pin || '' };
}

/** Only https boxes, except a plain-http address on a private LAN for testing. */
export function boxUrlProblem(url: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return 'That box address does not look right.';
  }
  if (parsed.protocol === 'https:') return null;
  if (parsed.protocol === 'http:' && isPrivateHost(parsed.hostname)) return null;
  return 'Use the https address your box shows.';
}

export function isPrivateHost(host: string): boolean {
  if (host === 'localhost' || host.endsWith('.local')) return true;
  const m = host.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a === 10 || a === 127 || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31);
}
