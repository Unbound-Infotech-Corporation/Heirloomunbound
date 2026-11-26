// Pins the box's TLS public key (from the pairing QR). The phone must also trust the box CA
// (see docs/MOBILE.md). Pinning is native code: it is active in dev/production builds, not Expo Go.
import { Platform } from 'react-native';

export async function pinBox(box: string, pin: string): Promise<boolean> {
  if (!pin || !box.startsWith('https://') || Platform.OS === 'web') return false;
  try {
    const mod = await import('react-native-ssl-public-key-pinning');
    if (!mod.isSslPinningAvailable()) return false;
    const host = new URL(box).hostname;
    // TrustKit (iOS) wants two hashes; the second is the same key, so only the box key is accepted.
    await mod.initializeSslPinning({ [host]: { includeSubdomains: false, publicKeyHashes: [pin, pin] } });
    return true;
  } catch {
    return false;
  }
}
