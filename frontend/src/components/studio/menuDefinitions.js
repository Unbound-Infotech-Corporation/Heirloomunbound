/** Per-document-window menus (Photoshop-style), keyed by route. */

function go(navigate, to) {
  return () => navigate(to);
}

function commonWindow(navigate) {
  return {
    label: "Window",
    items: [
      { label: "Today", onClick: go(navigate, "/today") },
      { label: "Archive", onClick: go(navigate, "/dashboard") },
      { label: "Sit", onClick: go(navigate, "/owner"), hint: "one teammate" },
      { label: "Twin", onClick: go(navigate, "/twin"), hint: "conversation" },
      { label: "Memory Studio", onClick: go(navigate, "/memory"), hint: "what the Twin holds" },
      { label: "First gift", onClick: go(navigate, "/first-gift"), hint: "sealed letter" },
      { label: "Mixer", onClick: go(navigate, "/mixer"), hint: "audio I/O" },
      { label: "Models", onClick: go(navigate, "/models"), hint: "provision" },
      { sep: true },
      { label: "Voice journal", onClick: go(navigate, "/journal") },
      { label: "Sources", onClick: go(navigate, "/sources") },
      { label: "Photos", onClick: go(navigate, "/photos") },
      { sep: true },
      { label: "Local PC", onClick: go(navigate, "/companion") },
      { label: "Settings", onClick: go(navigate, "/settings") },
    ],
  };
}

function audioMenu(navigate) {
  return {
    label: "Audio",
    items: [
      { label: "Mixer…", onClick: go(navigate, "/mixer"), hint: "devices · gain" },
      { label: "Live listen", onClick: go(navigate, "/mixer") },
      { label: "Session volume", onClick: go(navigate, "/mixer") },
      { label: "Monitor input", onClick: go(navigate, "/mixer") },
    ],
  };
}

function modelsMenu(navigate) {
  return {
    label: "Models",
    items: [
      { label: "Provision on dedicated PC…", onClick: go(navigate, "/models") },
      { label: "Speech to text", onClick: go(navigate, "/models") },
      { label: "Twin LLM", onClick: go(navigate, "/models") },
      { label: "Voice synthesis", onClick: go(navigate, "/models") },
      { sep: true },
        { label: "Cloud credential…", onClick: go(navigate, "/models"), hint: "per feature" },
    ],
  };
}

function editMenu(navigate, logout, setCaptureOpen) {
  return {
    label: "Edit",
    items: [
      { label: "Quick capture", onClick: () => setCaptureOpen?.(true) },
      { label: "Import sources…", onClick: go(navigate, "/import") },
      { sep: true },
      { label: "Settings…", onClick: go(navigate, "/settings") },
      { label: "Sign out", onClick: logout },
    ],
  };
}

const ROUTE_MENUS = {
  "/today": (ctx) => [
    {
      label: "Today",
      items: [
        { label: "Refresh", onClick: () => window.location.reload() },
        { label: "Sit", onClick: go(ctx.navigate, "/owner") },
        { label: "Open twin", onClick: go(ctx.navigate, "/twin") },
        { label: "Write the first gift", onClick: go(ctx.navigate, "/first-gift") },
        { label: "Voice journal", onClick: go(ctx.navigate, "/journal") },
      ],
    },
    editMenu(ctx.navigate, ctx.logout, ctx.setCaptureOpen),
    commonWindow(ctx.navigate),
  ],
  "/dashboard": (ctx) => [
    {
      label: "Archive",
      items: [
        { label: "Search archive", onClick: go(ctx.navigate, "/dashboard") },
        { label: "Import…", onClick: go(ctx.navigate, "/import") },
        { label: "Sources", onClick: go(ctx.navigate, "/sources") },
        { label: "Library", onClick: go(ctx.navigate, "/library") },
      ],
    },
    editMenu(ctx.navigate, ctx.logout, ctx.setCaptureOpen),
    commonWindow(ctx.navigate),
  ],
  "/owner": (ctx) => [
    {
      label: "Sit",
      items: [
        { label: "Twin sitting…", onClick: go(ctx.navigate, "/twin") },
        { label: "Memory Studio…", onClick: go(ctx.navigate, "/memory") },
        { label: "Local PC…", onClick: go(ctx.navigate, "/companion") },
        { label: "Abilities", onClick: go(ctx.navigate, "/abilities") },
      ],
    },
    editMenu(ctx.navigate, ctx.logout, ctx.setCaptureOpen),
    commonWindow(ctx.navigate),
  ],
  "/memory": (ctx) => [
    {
      label: "Memory",
      items: [
        { label: "What I hold onto", onClick: go(ctx.navigate, "/memory") },
        { label: "How we work", onClick: go(ctx.navigate, "/memory#how-we-work") },
        { label: "Safe topics", onClick: go(ctx.navigate, "/memory#safe-topics") },
        { sep: true },
        { label: "Portrait", onClick: go(ctx.navigate, "/personality") },
        { label: "Settings…", onClick: go(ctx.navigate, "/settings") },
      ],
    },
    editMenu(ctx.navigate, ctx.logout, ctx.setCaptureOpen),
    commonWindow(ctx.navigate),
  ],
  "/twin": (ctx) => [
    {
      label: "Twin",
      items: [
        { label: "New conversation", onClick: () => window.location.reload() },
        { label: "Write the first gift…", onClick: go(ctx.navigate, "/first-gift") },
        { label: "Avatar studio…", onClick: go(ctx.navigate, "/avatar-studio") },
        { label: "Abilities", onClick: go(ctx.navigate, "/abilities") },
        { label: "Portrait", onClick: go(ctx.navigate, "/personality") },
        { label: "Memory Studio…", onClick: go(ctx.navigate, "/memory") },
      ],
    },
    audioMenu(ctx.navigate),
    modelsMenu(ctx.navigate),
    commonWindow(ctx.navigate),
  ],
  "/mixer": (ctx) => [
    {
      label: "Devices",
      items: [
        { label: "Refresh devices", onClick: () => window.location.reload() },
        { label: "Default input / output", onClick: go(ctx.navigate, "/mixer") },
      ],
    },
    {
      label: "Input",
      items: [
        { label: "Gain / gate / high-pass", onClick: go(ctx.navigate, "/mixer") },
        { label: "Live listen", onClick: go(ctx.navigate, "/mixer") },
        { label: "Monitor", onClick: go(ctx.navigate, "/mixer") },
      ],
    },
    {
      label: "Output",
      items: [
        { label: "Heirloom session volume", onClick: go(ctx.navigate, "/mixer") },
        { label: "Mute output", onClick: go(ctx.navigate, "/mixer") },
      ],
    },
    modelsMenu(ctx.navigate),
    commonWindow(ctx.navigate),
  ],
  "/models": (ctx) => [
    modelsMenu(ctx.navigate),
    audioMenu(ctx.navigate),
    {
      label: "Provision",
      items: [
        { label: "Download missing models", onClick: go(ctx.navigate, "/models") },
        { label: "Refresh probe", onClick: () => window.location.reload() },
        { label: "Local PC companion", onClick: go(ctx.navigate, "/companion") },
      ],
    },
    commonWindow(ctx.navigate),
  ],
  "/journal": (ctx) => [
    {
      label: "Journal",
      items: [
        { label: "Choose microphone…", onClick: go(ctx.navigate, "/mixer") },
        { label: "Sample rate", onClick: go(ctx.navigate, "/mixer") },
        { label: "Library", onClick: go(ctx.navigate, "/library") },
      ],
    },
    audioMenu(ctx.navigate),
    modelsMenu(ctx.navigate),
    commonWindow(ctx.navigate),
  ],
  "/photos": (ctx) => [
    {
      label: "Photos",
      items: [
        { label: "Import…", onClick: go(ctx.navigate, "/import") },
        { label: "Photo → Story", onClick: go(ctx.navigate, "/photo-story") },
        { label: "Sources", onClick: go(ctx.navigate, "/sources") },
      ],
    },
    editMenu(ctx.navigate, ctx.logout, ctx.setCaptureOpen),
    commonWindow(ctx.navigate),
  ],
  "/sources": (ctx) => [
    {
      label: "Sources",
      items: [
        { label: "Add source", onClick: go(ctx.navigate, "/sources") },
        { label: "Import folder", onClick: go(ctx.navigate, "/import") },
        { label: "Local PC sync", onClick: go(ctx.navigate, "/companion") },
      ],
    },
    editMenu(ctx.navigate, ctx.logout, ctx.setCaptureOpen),
    commonWindow(ctx.navigate),
  ],
  "/companion": (ctx) => [
    {
      label: "Companion",
      items: [
        { label: "Refresh status", onClick: () => window.location.reload() },
        { label: "Models / provision", onClick: go(ctx.navigate, "/models") },
        { label: "Mixer", onClick: go(ctx.navigate, "/mixer") },
      ],
    },
    modelsMenu(ctx.navigate),
    audioMenu(ctx.navigate),
    commonWindow(ctx.navigate),
  ],
  "/letters": (ctx) => [
    {
      label: "Letters",
      items: [
        { label: "Write the first gift…", onClick: go(ctx.navigate, "/first-gift") },
        { label: "New sealed letter", onClick: go(ctx.navigate, "/letters?gift=1") },
        { label: "Heirs", onClick: go(ctx.navigate, "/heirs") },
      ],
    },
    editMenu(ctx.navigate, ctx.logout, ctx.setCaptureOpen),
    commonWindow(ctx.navigate),
  ],
  "/first-gift": (ctx) => [
    {
      label: "Gift",
      items: [
        { label: "Write mine", onClick: go(ctx.navigate, "/letters?gift=1") },
        { label: "Sealed letters", onClick: go(ctx.navigate, "/letters") },
        { label: "Sit with Twin", onClick: go(ctx.navigate, "/twin") },
      ],
    },
    editMenu(ctx.navigate, ctx.logout, ctx.setCaptureOpen),
    commonWindow(ctx.navigate),
  ],
  "/settings": (ctx) => [
    {
      label: "Settings",
      items: [
        { label: "Credentials", onClick: go(ctx.navigate, "/models"), hint: "inside each feature tab" },
        { label: "Memory Studio…", onClick: go(ctx.navigate, "/memory") },
        { label: "Heirs", onClick: go(ctx.navigate, "/heirs") },
        { label: "Sealed letters", onClick: go(ctx.navigate, "/letters") },
        { label: "First gift…", onClick: go(ctx.navigate, "/first-gift") },
      ],
    },
    editMenu(ctx.navigate, ctx.logout, ctx.setCaptureOpen),
    commonWindow(ctx.navigate),
  ],
};

export function getWindowMenus(pathname, ctx) {
  const factory = ROUTE_MENUS[pathname];
  if (factory) return factory(ctx);
  return [
    editMenu(ctx.navigate, ctx.logout, ctx.setCaptureOpen),
    audioMenu(ctx.navigate),
    modelsMenu(ctx.navigate),
    commonWindow(ctx.navigate),
  ];
}

export function getAppMenubarItems(ctx) {
  return [
    {
      label: "File",
      items: [
        { label: "Quick capture", onClick: () => ctx.setCaptureOpen?.((v) => !v) },
        { label: "Import…", onClick: go(ctx.navigate, "/import") },
        { sep: true },
        { label: "Sign out", onClick: ctx.logout },
      ],
    },
    {
      label: "Edit",
      items: [
        { label: "Settings…", onClick: go(ctx.navigate, "/settings") },
        { label: "Memory Studio…", onClick: go(ctx.navigate, "/memory") },
        { label: "Models / credentials", onClick: go(ctx.navigate, "/models") },
        { label: "First-run setup…", onClick: go(ctx.navigate, "/setup") },
        { label: "First gift…", onClick: go(ctx.navigate, "/first-gift") },
      ],
    },
    {
      label: "Window",
      items: commonWindow(ctx.navigate).items,
    },
    audioMenu(ctx.navigate),
    modelsMenu(ctx.navigate),
  ];
}
