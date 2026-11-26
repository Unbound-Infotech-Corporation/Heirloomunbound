import * as SecureStore from 'expo-secure-store';
import type { Session } from './api';

const KEY = 'heirloom.session.v1';

export async function loadSession(): Promise<Session | null> {
  const raw = await SecureStore.getItemAsync(KEY);
  if (!raw) return null;
  try {
    const s = JSON.parse(raw) as Session;
    return s.box && s.token ? s : null;
  } catch {
    return null;
  }
}

export async function saveSession(s: Session): Promise<void> {
  await SecureStore.setItemAsync(KEY, JSON.stringify(s));
}

export async function forgetSession(): Promise<void> {
  await SecureStore.deleteItemAsync(KEY);
}
