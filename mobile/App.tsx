import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { CameraView, useCameraPermissions } from 'expo-camera';
import {
  AudioModule, RecordingPresets, setAudioModeAsync, useAudioPlayer, useAudioRecorder, useAudioRecorderState,
} from 'expo-audio';
import { BoxClient, BoxError, claim, type Session } from './src/api';
import { boxUrlProblem, displayCode, normalizeBoxUrl, normalizeCode, parseQr } from './src/pairing';
import { pinBox } from './src/pinning';
import { forgetSession, loadSession, saveSession } from './src/store';

type Line = { who: 'you' | 'twin'; text: string };

export default function App() {
  const [session, setSession] = useState<Session | null | undefined>(undefined);

  useEffect(() => {
    loadSession().then(async (s) => {
      if (s) await pinBox(s.box, s.pin);
      setSession(s);
    });
  }, []);

  if (session === undefined) return <Centered><ActivityIndicator /></Centered>;
  return (
    <View style={styles.root}>
      <StatusBar style="light" />
      {session ? (
        <Home session={session} onUnpair={async () => { await forgetSession(); setSession(null); }} />
      ) : (
        <Pair onPaired={setSession} />
      )}
    </View>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return <View style={[styles.root, styles.center]}>{children}</View>;
}

function Pair({ onPaired }: { onPaired: (s: Session) => void }) {
  const [box, setBox] = useState('');
  const [code, setCode] = useState('');
  const [pin, setPin] = useState('');
  const [scanning, setScanning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [permission, requestPermission] = useCameraPermissions();
  const scanned = useRef(false);

  const pair = async (boxUrl: string, rawCode: string, pinValue: string) => {
    const url = normalizeBoxUrl(boxUrl);
    const problem = boxUrlProblem(url);
    if (problem) return Alert.alert('Box address', problem);
    if (normalizeCode(rawCode).length !== 8) return Alert.alert('Code', 'The code has 8 letters and numbers.');
    setBusy(true);
    try {
      await pinBox(url, pinValue);
      const platform = Platform.OS === 'ios' ? 'ios' : 'android';
      const s = await claim(url, normalizeCode(rawCode), platform, Platform.OS === 'ios' ? 'iPhone' : 'Android phone', pinValue);
      await saveSession(s);
      onPaired(s);
    } catch (e) {
      Alert.alert('Could not pair', e instanceof BoxError ? e.message : 'The phone could not reach your box. Is it on the same Wi-Fi, and does the phone trust the box certificate?');
    } finally {
      setBusy(false);
    }
  };

  if (scanning) {
    return (
      <View style={styles.root}>
        <CameraView
          style={{ flex: 1 }}
          barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
          onBarcodeScanned={({ data }) => {
            if (scanned.current) return;
            const p = parseQr(data);
            if (!p) return;
            scanned.current = true;
            setScanning(false);
            setBox(p.box); setCode(displayCode(p.code)); setPin(p.pin);
            pair(p.box, p.code, p.pin);
          }}
        />
        <Button label="Cancel" onPress={() => setScanning(false)} />
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.pad}>
      <Text style={styles.title}>Pair with your Heirloom box</Text>
      <Text style={styles.muted}>In Heirloom on your computer, open Pair a phone (/phone-app) and tap “Show pairing code”. Scan the code it shows, or type the address and code.</Text>
      <Button label="Scan the QR code" onPress={async () => {
        const ok = permission?.granted || (await requestPermission()).granted;
        if (ok) { scanned.current = false; setScanning(true); }
      }} />
      <TextInput style={styles.input} placeholder="Box address, e.g. https://192.168.1.20:8443" placeholderTextColor="#889"
        autoCapitalize="none" autoCorrect={false} value={box} onChangeText={setBox} />
      <TextInput style={styles.input} placeholder="Code, e.g. ABCD-EFGH" placeholderTextColor="#889"
        autoCapitalize="characters" autoCorrect={false} value={code} onChangeText={setCode} />
      {busy ? <ActivityIndicator /> : <Button label="Pair" onPress={() => pair(box, code, pin)} />}
      <Text style={styles.small}>Your phone only talks to your own box. Nothing goes to a cloud AI.</Text>
    </ScrollView>
  );
}

function Home({ session, onUnpair }: { session: Session; onUnpair: () => void }) {
  const client = useRef(new BoxClient(session)).current;
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(true);
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recState = useAudioRecorderState(recorder);
  const player = useAudioPlayer(null);

  useEffect(() => {
    client.me().catch((e) => {
      if (e instanceof BoxError && (e.status === 401 || e.status === 403)) {
        Alert.alert('Unpaired', 'This phone was removed on the box. Pair again.');
        onUnpair();
      }
    });
  }, []);

  const say = (reply: string) => {
    if (!speakReplies || !reply) return;
    player.replace(client.speakSource(reply));
    player.play();
  };

  const send = async () => {
    const t = text.trim();
    if (!t || busy) return;
    setText(''); setBusy(true);
    setLines((l) => [...l, { who: 'you', text: t }]);
    try {
      const r = await client.chat(t);
      setLines((l) => [...l, { who: 'twin', text: r.reply }]);
      say(r.reply);
    } catch (e) {
      setLines((l) => [...l, { who: 'twin', text: e instanceof BoxError ? e.message : 'Could not reach your box.' }]);
    } finally {
      setBusy(false);
    }
  };

  const talk = async () => {
    if (recState.isRecording) {
      await recorder.stop();
      const uri = recorder.uri;
      if (!uri) return;
      setBusy(true);
      try {
        const r = await client.voice(uri);
        setLines((l) => [...l, { who: 'you', text: r.userText || '(voice)' }, { who: 'twin', text: r.reply }]);
        say(r.reply);
      } catch (e) {
        setLines((l) => [...l, { who: 'twin', text: e instanceof BoxError ? e.message : 'Could not reach your box.' }]);
      } finally {
        setBusy(false);
      }
      return;
    }
    const perm = await AudioModule.requestRecordingPermissionsAsync();
    if (!perm.granted) return Alert.alert('Microphone', 'Allow the microphone to talk to your Twin.');
    await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: true });
    await recorder.prepareToRecordAsync();
    recorder.record();
  };

  return (
    <KeyboardAvoidingView style={styles.root} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={styles.header}>
        <Text style={styles.title}>Your Twin</Text>
        <Pressable onPress={() => Alert.alert('Unpair this phone?', 'You can pair again with a new code.', [
          { text: 'Cancel', style: 'cancel' }, { text: 'Unpair', style: 'destructive', onPress: onUnpair },
        ])}><Text style={styles.link}>Unpair</Text></Pressable>
      </View>
      <ScrollView style={{ flex: 1 }} contentContainerStyle={styles.pad}>
        {lines.map((l, i) => (
          <Text key={i} style={l.who === 'you' ? styles.you : styles.twin}>{l.text}</Text>
        ))}
        {busy && <ActivityIndicator />}
      </ScrollView>
      <View style={styles.row}>
        <TextInput style={[styles.input, { flex: 1 }]} placeholder="Say something" placeholderTextColor="#889"
          value={text} onChangeText={setText} onSubmitEditing={send} />
        <Button label="Send" onPress={send} />
      </View>
      <View style={styles.row}>
        <Button label={recState.isRecording ? 'Stop and send' : 'Talk'} onPress={talk} />
        <Pressable onPress={() => setSpeakReplies((v) => !v)}>
          <Text style={styles.link}>{speakReplies ? 'Voice on' : 'Voice off'}</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

function Button({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable style={styles.button} onPress={onPress} accessibilityRole="button">
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#14161c', paddingTop: 48 },
  center: { alignItems: 'center', justifyContent: 'center' },
  pad: { padding: 20, gap: 12 },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 20 },
  title: { color: '#f3ead8', fontSize: 22, fontWeight: '600' },
  muted: { color: '#b9b4a8', fontSize: 15 },
  small: { color: '#8d897f', fontSize: 13, marginTop: 8 },
  input: { backgroundColor: '#20232b', color: '#f3ead8', borderRadius: 10, padding: 12, fontSize: 16 },
  button: { backgroundColor: '#c8a25a', borderRadius: 10, paddingVertical: 12, paddingHorizontal: 18, alignItems: 'center' },
  buttonText: { color: '#14161c', fontSize: 16, fontWeight: '600' },
  link: { color: '#c8a25a', fontSize: 15 },
  row: { flexDirection: 'row', gap: 10, alignItems: 'center', paddingHorizontal: 20, paddingBottom: 12 },
  you: { color: '#f3ead8', alignSelf: 'flex-end', backgroundColor: '#2b2f3a', padding: 10, borderRadius: 10, maxWidth: '85%' },
  twin: { color: '#14161c', alignSelf: 'flex-start', backgroundColor: '#e9dcc0', padding: 10, borderRadius: 10, maxWidth: '85%' },
});
