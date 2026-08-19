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
    every[monitorId] = Math.min(1440, Math.max(1, Math.round(Number(arg) || DEFAULT_MINUTES)));
    ctx.store.every = every;
  }
});

plugin.render((ctx) => {
  if (!ctx.target) return null;
  const on = (ctx.store.on || {})[ctx.target] === true;
  const every = (ctx.store.every || {})[ctx.target] || DEFAULT_MINUTES;
  const seen = (ctx.store.counts || {})[ctx.target] || { alerts: 0, frames: 0 };
  return {
    type: "col",
    children: [
      { type: "toggle", label: "Send progress reports", on: on, action: "on:" + ctx.target },
      on && {
        type: "input",
        kind: "number",
        label: "Report every, in minutes",
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
