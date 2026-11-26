import { boxUrlProblem, displayCode, isPrivateHost, normalizeBoxUrl, normalizeCode, parseQr } from '../src/pairing';

describe('pairing QR (same format as backend/mobile_pairing.qr_payload)', () => {
  it('parses the box QR, with url-encoded box and pin', () => {
    // python: urlencode({"box": "https://192.168.0.110:8443", "code": "ABCD2345", "pin": "a+b/c="})
    const qr = 'heirloom://pair?box=https%3A%2F%2F192.168.0.110%3A8443&code=ABCD2345&pin=a%2Bb%2Fc%3D';
    expect(parseQr(qr)).toEqual({ box: 'https://192.168.0.110:8443', code: 'ABCD2345', pin: 'a+b/c=' });
  });
  it('rejects other QR codes', () => {
    expect(parseQr('https://example.com')).toBeNull();
    expect(parseQr('heirloom://pair?box=ftp%3A%2F%2Fx&code=ABCD2345')).toBeNull();
    expect(parseQr('heirloom://pair?box=https%3A%2F%2Fx&code=ABC')).toBeNull();
    expect(parseQr('')).toBeNull();
  });
  it('normalizes typed codes and addresses', () => {
    expect(normalizeCode(' abcd-2345 ')).toBe('ABCD2345');
    expect(displayCode('abcd2345')).toBe('ABCD-2345');
    expect(normalizeBoxUrl('192.168.1.20:8443/')).toBe('https://192.168.1.20:8443');
  });
  it('only allows https, or http on a private LAN', () => {
    expect(boxUrlProblem('https://box.example')).toBeNull();
    expect(boxUrlProblem('http://192.168.1.20:8000')).toBeNull();
    expect(boxUrlProblem('http://example.com')).not.toBeNull();
    expect(boxUrlProblem('not a url')).not.toBeNull();
    expect(isPrivateHost('172.20.0.1')).toBe(true);
    expect(isPrivateHost('172.40.0.1')).toBe(false);
  });
});
