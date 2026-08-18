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
  const [what, monitorId] = name.split(":");
  if (what === "on") {
    const on = ctx.store.on || {};
    on[monitorId] = arg === true;
    ctx.store.on = on;
  }
  if (what === "sound") {
    const sound = ctx.store.sound || {};
    sound[monitorId] = arg;
    ctx.store.sound = sound;
    ctx.sound(SOUNDS.get(arg) || HORN);
  }
});

plugin.render((ctx) => {
  const on = ctx.store.on || {};
  const sound = ctx.store.sound || {};

  if (ctx.target) {
    return {
      type: "col",
      children: [
        { type: "toggle", label: "Sound an alert", on: on[ctx.target] === true, action: "on:" + ctx.target },
        on[ctx.target] === true && {
          type: "select",
          label: "Alert sound",
          value: sound[ctx.target] || names[0],
          action: "sound:" + ctx.target,
          options: names.map((name) => ({ value: name, label: name })),
        },
      ],
    };
  }

  const heard = ctx.store.heard || {};
  for (const monitor of ctx.state.monitors || []) {
    const at = monitor.alert ? monitor.alert.ts : 0;
    if (at !== heard[monitor.id] && at && on[monitor.id]) ctx.sound(SOUNDS.get(sound[monitor.id]) || HORN);
    heard[monitor.id] = at;
  }
  ctx.store.heard = heard;
  return null;
});
