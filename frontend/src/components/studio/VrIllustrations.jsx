/** Static SVG diagrams for the Rooms VR setup coach. */

function Frame({ children, label }) {
  return (
    <figure className="vr-art" data-testid={`vr-art-${label}`}>
      <svg viewBox="0 0 160 110" width="100%" height="110" aria-hidden="true">
        <rect x="0.5" y="0.5" width="159" height="109" rx="4" fill="#1a1a1a" stroke="#3a3a3a" />
        {children}
      </svg>
    </figure>
  );
}

export function QuestArt() {
  return (
    <Frame label="quest">
      <rect x="48" y="28" width="64" height="36" rx="12" fill="#2a241c" stroke="#c9b8a4" />
      <rect x="54" y="34" width="22" height="16" rx="3" fill="#111" />
      <rect x="84" y="34" width="22" height="16" rx="3" fill="#111" />
      <rect x="42" y="40" width="8" height="12" rx="2" fill="#8a7358" />
      <rect x="110" y="40" width="8" height="12" rx="2" fill="#8a7358" />
      <path d="M80 70 v18" stroke="#d4a373" strokeWidth="2" />
      <path d="M80 88 h28" stroke="#d4a373" strokeWidth="2" />
      <rect x="108" y="84" width="18" height="10" rx="1" fill="#222" stroke="#4da3ff" />
    </Frame>
  );
}

export function IndexArt() {
  return (
    <Frame label="index">
      <rect x="58" y="24" width="44" height="40" rx="6" fill="#2a241c" stroke="#c9b8a4" />
      <circle cx="74" cy="44" r="7" fill="#111" />
      <circle cx="90" cy="44" r="7" fill="#111" />
      <rect x="36" y="70" width="16" height="22" rx="2" fill="#444" stroke="#888" />
      <rect x="108" y="70" width="16" height="22" rx="2" fill="#444" stroke="#888" />
      <path d="M80 64 v12" stroke="#4da3ff" strokeWidth="2" />
      <text x="80" y="102" textAnchor="middle" fill="#888" fontSize="8">
        DP + lighthouse
      </text>
    </Frame>
  );
}

export function WmrArt() {
  return (
    <Frame label="wmr">
      <rect x="44" y="30" width="72" height="32" rx="10" fill="#2a241c" stroke="#888" />
      <text x="80" y="50" textAnchor="middle" fill="#c95a5a" fontSize="9">
        deprecated
      </text>
      <rect x="52" y="72" width="56" height="18" rx="2" fill="#222" stroke="#d4a373" />
      <text x="80" y="84" textAnchor="middle" fill="#d4a373" fontSize="8">
        Oasis
      </text>
    </Frame>
  );
}

export function PicoArt() {
  return (
    <Frame label="pico">
      <rect x="50" y="30" width="60" height="32" rx="10" fill="#2a241c" stroke="#c9b8a4" />
      <circle cx="70" cy="46" r="6" fill="#111" />
      <circle cx="90" cy="46" r="6" fill="#111" />
      <path d="M40 88 q40 -28 80 0" fill="none" stroke="#4da3ff" strokeWidth="2" />
      <circle cx="80" cy="78" r="3" fill="#4da3ff" />
    </Frame>
  );
}

export function Psvr2Art() {
  return (
    <Frame label="psvr2">
      <rect x="28" y="38" width="44" height="28" rx="3" fill="#222" stroke="#c9b8a4" />
      <text x="50" y="56" textAnchor="middle" fill="#aaa" fontSize="8">
        adapter
      </text>
      <path d="M72 52 h18" stroke="#4da3ff" strokeWidth="2" />
      <rect x="92" y="34" width="40" height="36" rx="10" fill="#2a241c" stroke="#c9b8a4" />
      <text x="50" y="90" textAnchor="middle" fill="#888" fontSize="7">
        DP 1.4 + USB 3
      </text>
    </Frame>
  );
}

export function AlvrArt() {
  return (
    <Frame label="alvr">
      <rect x="24" y="32" width="44" height="30" rx="3" fill="#1f1f1f" stroke="#4da3ff" />
      <text x="46" y="50" textAnchor="middle" fill="#4da3ff" fontSize="8">
        PC
      </text>
      <path d="M70 48 h20" stroke="#d4a373" strokeWidth="2" strokeDasharray="3 3" />
      <rect x="92" y="30" width="44" height="34" rx="10" fill="#2a241c" stroke="#c9b8a4" />
    </Frame>
  );
}

export function VisionArt() {
  return (
    <Frame label="vision">
      <ellipse cx="80" cy="48" rx="40" ry="22" fill="#2a241c" stroke="#c9b8a4" />
      <text x="80" y="52" textAnchor="middle" fill="#888" fontSize="8">
        no macOS host
      </text>
      <rect x="36" y="78" width="88" height="16" rx="2" fill="#222" stroke="#555" />
      <text x="80" y="89" textAnchor="middle" fill="#d4a373" fontSize="8">
        Windows PC + ALVR
      </text>
    </Frame>
  );
}

export function CardboardArt() {
  return (
    <Frame label="cardboard">
      <rect x="40" y="28" width="80" height="52" rx="4" fill="#3a3228" stroke="#c9b8a4" />
      <rect x="52" y="40" width="24" height="28" rx="2" fill="#111" />
      <rect x="84" y="40" width="24" height="28" rx="2" fill="#111" />
      <text x="80" y="96" textAnchor="middle" fill="#888" fontSize="8">
        phone in viewer
      </text>
    </Frame>
  );
}

export function DownloadArt() {
  return (
    <Frame label="download">
      <rect x="58" y="22" width="44" height="36" rx="3" fill="#222" stroke="#4da3ff" />
      <path d="M80 34 v22" stroke="#d4a373" strokeWidth="3" />
      <path d="M70 48 l10 10 l10 -10" fill="none" stroke="#d4a373" strokeWidth="3" />
      <text x="80" y="90" textAnchor="middle" fill="#888" fontSize="8">
        official only
      </text>
    </Frame>
  );
}

export function CableArt() {
  return (
    <Frame label="cable">
      <rect x="24" y="44" width="36" height="18" rx="2" fill="#333" />
      <path d="M60 53 h40" stroke="#d4a373" strokeWidth="3" />
      <rect x="100" y="40" width="36" height="26" rx="4" fill="#2a241c" stroke="#c9b8a4" />
    </Frame>
  );
}

export function WifiArt() {
  return (
    <Frame label="wifi">
      <path d="M50 70 q30 -40 60 0" fill="none" stroke="#4da3ff" strokeWidth="2" />
      <path d="M62 70 q18 -22 36 0" fill="none" stroke="#4da3ff" strokeWidth="2" />
      <circle cx="80" cy="78" r="4" fill="#d4a373" />
    </Frame>
  );
}

export function OpenXrArt() {
  return (
    <Frame label="openxr">
      <circle cx="80" cy="48" r="26" fill="none" stroke="#4da3ff" strokeWidth="3" />
      <text x="80" y="52" textAnchor="middle" fill="#eee" fontSize="11">
        XR
      </text>
      <text x="80" y="92" textAnchor="middle" fill="#888" fontSize="8">
        one runtime
      </text>
    </Frame>
  );
}

export function WebXrArt() {
  return (
    <Frame label="webxr">
      <rect x="36" y="26" width="88" height="56" rx="4" fill="#111" stroke="#888" />
      <circle cx="80" cy="54" r="12" fill="none" stroke="#d4a373" strokeWidth="2" />
      <text x="80" y="98" textAnchor="middle" fill="#888" fontSize="8">
        browser
      </text>
    </Frame>
  );
}

export function SitArt() {
  return (
    <Frame label="sit">
      <rect x="28" y="62" width="104" height="8" fill="#3a3228" />
      <circle cx="80" cy="44" r="10" fill="#c9b8a4" />
      <rect x="70" y="54" width="20" height="16" rx="3" fill="#8a7358" />
    </Frame>
  );
}

export function CheckArt() {
  return (
    <Frame label="check">
      <circle cx="80" cy="50" r="22" fill="none" stroke="#d4a373" strokeWidth="3" />
      <path d="M68 50 l8 8 l16 -16" fill="none" stroke="#d4a373" strokeWidth="3" />
    </Frame>
  );
}

export function LockArt() {
  return (
    <Frame label="lock">
      <rect x="58" y="46" width="44" height="32" rx="4" fill="#222" stroke="#c95a5a" />
      <path d="M68 46 v-10 a12 12 0 0 1 24 0 v10" fill="none" stroke="#c95a5a" strokeWidth="3" />
    </Frame>
  );
}

export function BtArt() {
  return (
    <Frame label="bt">
      <path d="M80 24 l18 18 l-18 18 l18 18 l-18 18" fill="none" stroke="#4da3ff" strokeWidth="3" />
      <path d="M80 42 l-16 12" stroke="#4da3ff" strokeWidth="3" />
      <path d="M80 78 l-16 -12" stroke="#4da3ff" strokeWidth="3" />
    </Frame>
  );
}

const HEADSET = {
  quest: QuestArt,
  index: IndexArt,
  wmr: WmrArt,
  pico: PicoArt,
  psvr2: Psvr2Art,
  alvr: AlvrArt,
  vision: VisionArt,
  cardboard: CardboardArt,
};

const STEP = {
  download: DownloadArt,
  cable: CableArt,
  wifi: WifiArt,
  openxr: OpenXrArt,
  webxr: WebXrArt,
  sit: SitArt,
  check: CheckArt,
  lock: LockArt,
  bt: BtArt,
  quest: QuestArt,
  pico: PicoArt,
  psvr2: Psvr2Art,
  alvr: AlvrArt,
  wmr: WmrArt,
};

export function HeadsetArt({ id }) {
  const Comp = HEADSET[id] || QuestArt;
  return <Comp />;
}

export function StepArt({ id }) {
  const Comp = STEP[id] || DownloadArt;
  return <Comp />;
}
