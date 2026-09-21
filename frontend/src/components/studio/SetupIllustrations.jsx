/** Static SVG examples for Twin voice + likeness setup (Phase 1 art). */

function Frame({ children, label, done }) {
  return (
    <figure className={`setup-example ${done ? "is-done" : ""}`} data-testid={`setup-example-${label}`}>
      <svg viewBox="0 0 160 110" width="100%" height="110" aria-hidden="true">
        <rect x="0.5" y="0.5" width="159" height="109" rx="4" fill="#1a1a1a" stroke="#3a3a3a" />
        {children}
      </svg>
    </figure>
  );
}

export function VoiceQuietArt({ done }) {
  return (
    <Frame label="quiet" done={done}>
      <rect x="28" y="22" width="70" height="68" rx="3" fill="#2a241c" stroke="#6b5a45" />
      <rect x="86" y="38" width="18" height="36" rx="1" fill="#1a1a1a" stroke="#6b5a45" />
      <circle cx="52" cy="58" r="10" fill="#c9b8a4" />
      <rect x="44" y="68" width="16" height="18" rx="2" fill="#8a7358" />
      <rect x="108" y="30" width="28" height="52" rx="2" fill="#222" stroke="#555" />
      <text x="122" y="60" textAnchor="middle" fill="#888" fontSize="9">
        hush
      </text>
    </Frame>
  );
}

export function VoiceSpeakArt({ done }) {
  return (
    <Frame label="speak" done={done}>
      <circle cx="48" cy="52" r="16" fill="#c9b8a4" />
      <rect x="36" y="68" width="24" height="22" rx="3" fill="#8a7358" />
      <path d="M72 40 c18 8 18 34 0 42" fill="none" stroke="#4da3ff" strokeWidth="3" />
      <path d="M86 32 c28 14 28 54 0 68" fill="none" stroke="#4da3ff" strokeWidth="2" opacity="0.7" />
      <path d="M98 24 c36 18 36 70 0 88" fill="none" stroke="#4da3ff" strokeWidth="1.5" opacity="0.4" />
    </Frame>
  );
}

export function VoiceReadyArt({ done }) {
  return (
    <Frame label="ready" done={done}>
      <ellipse cx="80" cy="86" rx="42" ry="10" fill="#2a241c" />
      <circle cx="80" cy="48" r="22" fill="#c9b8a4" />
      <rect x="62" y="68" width="36" height="20" rx="4" fill="#8a7358" />
      <path d="M112 40 l8 0 m-4 -8 l0 16" stroke="#d4a373" strokeWidth="2" />
      <path d="M124 36 l10 0 m-5 -10 l0 20" stroke="#d4a373" strokeWidth="2" opacity="0.6" />
    </Frame>
  );
}

export function LikenessFrontArt({ done }) {
  return (
    <Frame label="front" done={done}>
      <rect x="50" y="18" width="60" height="78" rx="22" fill="#2a241c" stroke="#6b5a45" />
      <circle cx="80" cy="48" r="18" fill="#c9b8a4" />
      <circle cx="73" cy="46" r="2.5" fill="#1a1a1a" />
      <circle cx="87" cy="46" r="2.5" fill="#1a1a1a" />
      <path d="M74 56 q6 5 12 0" fill="none" stroke="#1a1a1a" strokeWidth="1.5" />
      <rect x="64" y="68" width="32" height="24" rx="6" fill="#8a7358" />
    </Frame>
  );
}

export function LikenessThreeQuarterArt({ done }) {
  return (
    <Frame label="three_quarter" done={done}>
      <ellipse cx="86" cy="50" rx="20" ry="22" fill="#2a241c" />
      <ellipse cx="90" cy="48" rx="16" ry="18" fill="#c9b8a4" />
      <circle cx="96" cy="46" r="2.2" fill="#1a1a1a" />
      <path d="M92 56 q6 4 10 -1" fill="none" stroke="#1a1a1a" strokeWidth="1.4" />
      <rect x="74" y="68" width="28" height="22" rx="6" fill="#8a7358" />
      <path d="M44 78 L70 40" stroke="#4da3ff" strokeWidth="1.5" opacity="0.5" />
    </Frame>
  );
}

export function LikenessProfileArt({ done }) {
  return (
    <Frame label="profile" done={done}>
      <path
        d="M70 22 q28 6 32 28 q4 22 -10 36 q-8 8 -22 10 v-74 z"
        fill="#c9b8a4"
        stroke="#6b5a45"
      />
      <circle cx="92" cy="44" r="2" fill="#1a1a1a" />
      <path d="M96 52 q8 2 6 8" fill="none" stroke="#1a1a1a" strokeWidth="1.4" />
      <rect x="58" y="72" width="30" height="20" rx="5" fill="#8a7358" />
    </Frame>
  );
}

export function AvatarPickArt({ done }) {
  return (
    <Frame label="pick" done={done}>
      <rect x="36" y="20" width="88" height="70" rx="4" fill="#111" stroke="#4da3ff" />
      <circle cx="80" cy="48" r="16" fill="#c9b8a4" />
      <rect x="64" y="64" width="32" height="18" rx="4" fill="#8a7358" />
      <text x="80" y="96" textAnchor="middle" fill="#4da3ff" fontSize="8">
        use this face
      </text>
    </Frame>
  );
}

const ART = {
  quiet: VoiceQuietArt,
  speak: VoiceSpeakArt,
  ready: VoiceReadyArt,
  front: LikenessFrontArt,
  three_quarter: LikenessThreeQuarterArt,
  profile: LikenessProfileArt,
  pick: AvatarPickArt,
};

export function SetupExampleArt({ exampleId, done }) {
  const Comp = ART[exampleId] || VoiceQuietArt;
  return <Comp done={done} />;
}

export function SetupExampleRow({ examples, done }) {
  return (
    <div className="setup-example-row" data-testid="setup-examples">
      {(examples || []).map((ex) => (
        <div key={ex.id} className="setup-example-card">
          <SetupExampleArt exampleId={ex.id} done={done} />
          <p className="setup-example-title">{ex.title}</p>
          <p className="setup-example-caption">{ex.caption}</p>
        </div>
      ))}
    </div>
  );
}
