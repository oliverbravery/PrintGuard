plugin.action((name, arg, ctx) => {
  if (name !== "float") return;
  ctx.store.picked = arg;
  ctx.float(true);
});

plugin.render((ctx) => {
  if (!ctx.target) return { type: "camera", camera_id: ctx.store.picked };
  const monitor = (ctx.state.monitors || []).find((candidate) => candidate.id === ctx.target);
  if (!monitor || !monitor.camera_id) return null;
  return { type: "button", label: "⧉", action: "float", arg: monitor.camera_id };
});
