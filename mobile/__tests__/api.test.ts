import { BoxClient, BoxError, claim } from '../src/api';

type Call = { url: string; init: any };
function fakeFetch(responses: Array<{ status: number; body: any }>) {
  const calls: Call[] = [];
  const f = (async (url: string, init: any) => {
    calls.push({ url, init });
    const r = responses.shift()!;
    return { ok: r.status < 400, status: r.status, json: async () => r.body } as any;
  }) as unknown as typeof fetch;
  return { f, calls };
}

describe('box API client', () => {
  it('claims a code and returns a session', async () => {
    const { f, calls } = fakeFetch([{ status: 200, body: { device_id: 'phone_ab', device_token: 'mob_x', name: 'iPhone' } }]);
    const s = await claim('https://box', 'ABCD2345', 'ios', 'iPhone', 'pin=', f);
    expect(s).toEqual({ box: 'https://box', token: 'mob_x', deviceId: 'phone_ab', name: 'iPhone', pin: 'pin=' });
    expect(calls[0].url).toBe('https://box/api/mobile/pair/claim');
    expect(JSON.parse(calls[0].init.body)).toEqual({ code: 'ABCD2345', platform: 'ios', device_name: 'iPhone' });
    expect(calls[0].init.headers.Authorization).toBeUndefined();
  });
  it('surfaces the box error text', async () => {
    const { f } = fakeFetch([{ status: 404, body: { detail: 'That code is wrong, used or expired.' } }]);
    await expect(claim('https://box', 'ABCD2345', 'android', '', '', f)).rejects.toEqual(
      new BoxError(404, 'That code is wrong, used or expired.'));
  });
  it('chats through /api/desktop/chat with the phone token', async () => {
    const { f, calls } = fakeFetch([{ status: 200, body: { reply: 'Hello.' } }]);
    const c = new BoxClient({ box: 'https://box', token: 'mob_x', deviceId: 'd', name: 'n', pin: '' }, f);
    expect(await c.chat('hi')).toEqual({ reply: 'Hello.' });
    expect(calls[0].url).toBe('https://box/api/desktop/chat');
    expect(calls[0].init.headers.Authorization).toBe('Bearer mob_x');
    expect(JSON.parse(calls[0].init.body)).toEqual({ text: 'hi', mode: 'twin' });
  });
  it('builds a streamable speak source with the header', () => {
    const c = new BoxClient({ box: 'https://box', token: 'mob_x', deviceId: 'd', name: 'n', pin: '' });
    const src = c.speakSource('Hi & bye');
    expect(src.uri).toBe('https://box/api/mobile/speak.wav?text=Hi%20%26%20bye');
    expect(src.headers).toEqual({ Authorization: 'Bearer mob_x' });
  });
  it('sends voice to /api/companion/voice', async () => {
    const { f, calls } = fakeFetch([{ status: 200, body: { reply: 'Yes.', user_text: 'is it on' } }]);
    const c = new BoxClient({ box: 'https://box', token: 'mob_x', deviceId: 'd', name: 'n', pin: '' }, f);
    expect(await c.voice('file:///cache/rec.m4a')).toEqual({ reply: 'Yes.', userText: 'is it on' });
    expect(calls[0].url).toBe('https://box/api/companion/voice');
  });
});
