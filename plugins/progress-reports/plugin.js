// The panel half. It shares one ctx.store with worker.js, so the switch and the
// interval set here are what the worker reads when its timer comes round, and the
// tally the worker keeps is what gets shown back.
const DEFAULT_MINUTES = 30;

plugin.action((name, arg, ctx) => {
  const [what, monitorId] = name.split(":");
  if (what === "on") {
    const on = ctx.store.on || {};
    on[monitorId] = arg === true;
    ctx.store.on = on;
  }
  if (what === "every") {
    const every = ctx.store.every || {};
    // A number input hands over whatever was typed, so clamp it on the way in. A
    // minute at the least and a day at the most.
    every[monitorId] = Math.min(1440, Math.max(1, Math.round(Number(arg) || DEFAULT_MINUTES)));
    ctx.store.every = every;
  }
});

plugin.render((ctx) => {
  // The settings surface calls render once more without ctx.target, for a panel
  // this plugin does not have, so there is nothing to draw that time.
  if (!ctx.target) return null;
  const on = (ctx.store.on || {})[ctx.target] === true;
  const every = (ctx.store.every || {})[ctx.target] || DEFAULT_MINUTES;
  const seen = (ctx.store.counts || {})[ctx.target] || { alerts: 0, frames: 0 };
  return {
    type: "col",
    children: [
      { type: "toggle", label: "Send progress reports", on: on, action: "on:" + ctx.target },
      // An input commits on blur or Enter rather than on every keystroke, and a
      // false child is dropped, so the interval only appears once reports are on.
      on && {
        type: "input",
        kind: "number",
        label: "Minutes between each notification",
        value: String(every),
        action: "every:" + ctx.target,
      },
      on && {
        type: "text",
        muted: true,
        value: "This print: " + seen.alerts + " alerts, " + seen.frames + " frames over the threshold",
      },
    ],
  };
});
