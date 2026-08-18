const HORN = [
  { hz: 196, ms: 700, shape: "sawtooth", together: false },
  { hz: 233, ms: 700, shape: "sawtooth", together: true },
];

const SOUNDS = new Map([
  ["horn", HORN],
  [
    "bell",
    [
      { hz: 880, ms: 1400, shape: "sine", together: false },
      { hz: 1320, ms: 1100, shape: "sine", together: true },
      { hz: 2640, ms: 700, shape: "sine", together: true },
    ],
  ],
  [
    "alarm",
    [
      { hz: 880, ms: 160, shape: "square", together: false },
      { hz: 660, ms: 160, shape: "square", together: false },
      { hz: 880, ms: 160, shape: "square", together: false },
      { hz: 660, ms: 160, shape: "square", together: false },
    ],
  ],
]);

const names = [...SOUNDS.keys()];

plugin.action((name, arg, ctx) => {
  if (name === "sound") ctx.store.sound = arg;
  if (name === "test") ctx.sound(SOUNDS.get(ctx.store.sound) || HORN);
  if (name !== "toggle") return;
  const on = ctx.store.on || {};
  on[arg] = !on[arg];
  ctx.store.on = on;
});

plugin.render((ctx) => {
  const on = ctx.store.on || {};
  const monitors = ctx.state.monitors || [];

  if (ctx.target) {
    return { type: "button", label: on[ctx.target] ? "🔊" : "🔇", action: "toggle", arg: ctx.target };
  }

  const heard = ctx.store.heard || {};
  for (const monitor of monitors) {
    const at = monitor.alert ? monitor.alert.ts : 0;
    if (at !== heard[monitor.id] && at && on[monitor.id]) ctx.sound(SOUNDS.get(ctx.store.sound) || HORN);
    heard[monitor.id] = at;
  }
  ctx.store.heard = heard;

  const listening = monitors.filter((monitor) => on[monitor.id]).map((monitor) => monitor.name);
  return {
    type: "col",
    children: [
      {
        type: "row",
        children: [
          {
            type: "select",
            label: "Sound",
            value: ctx.store.sound || names[0],
            action: "sound",
            options: names.map((sound) => ({ value: sound, label: sound })),
          },
          { type: "button", label: "Test", action: "test" },
        ],
      },
      {
        type: "text",
        muted: true,
        value: listening.length ? "Sounding for " + listening.join(", ") : "Press the speaker on a monitor to sound for it.",
      },
    ],
  };
});
