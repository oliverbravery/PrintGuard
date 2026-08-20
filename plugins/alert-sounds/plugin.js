// A file runs inside a function with nothing else in scope, so there is no import,
// no fetch, no DOM and no storage. Top-level values like these last as long as the
// sandbox does, which is until the next reload, so nothing worth keeping lives here.

// ctx.sound takes tones rather than the name of a sound PrintGuard knows, so these
// three are the plugin's own. Each tone runs after the one before it unless it says
// together, which starts it alongside instead and is how a chord is built.
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

// One handler takes every press and choice, named by the node's action string and
// given its arg. Packing the monitor id into that name is how a plugin drawn once
// per monitor works out which one it is hearing from.
plugin.action((name, arg, ctx) => {
  const [what, monitorId] = name.split(":");
  if (what === "on") {
    // ctx.store is the plugin's own data, and PrintGuard saves it when it is
    // assigned to, so read it out, change it and put it back.
    const on = ctx.store.on || {};
    on[monitorId] = arg === true;
    ctx.store.on = on;
  }
  if (what === "sound") {
    const sound = ctx.store.sound || {};
    sound[monitorId] = arg;
    ctx.store.sound = sound;
    // Play the choice back, so picking a sound is how you hear it.
    ctx.sound(SOUNDS.get(arg) || HORN);
  }
});

plugin.render((ctx) => {
  const on = ctx.store.on || {};
  const sound = ctx.store.sound || {};

  // The settings surface calls render once per monitor with ctx.target naming
  // which, and once more without it for the plugin's own view.
  if (ctx.target) {
    return {
      type: "col",
      children: [
        { type: "toggle", label: "Sound an alert", on: on[ctx.target] === true, action: "on:" + ctx.target },
        // A false or null child is dropped, which is how a node appears only once
        // something else is switched on.
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

  // render runs on every state change whether or not there is a panel to draw, so
  // this is where a plugin with no panel of its own can still watch for something.
  // Each monitor's alert carries the moment it fired, and comparing that against
  // the last one seen catches a new alert exactly once.
  const heard = ctx.store.heard || {};
  for (const monitor of ctx.state.monitors || []) {
    const at = monitor.alert ? monitor.alert.ts : 0;
    if (at !== heard[monitor.id] && at && on[monitor.id]) ctx.sound(SOUNDS.get(sound[monitor.id]) || HORN);
    heard[monitor.id] = at;
  }
  ctx.store.heard = heard;
  return null;
});
