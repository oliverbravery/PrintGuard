plugin.action((name, arg, ctx) => {
  if (name !== "monitor") return;
  const monitor = (ctx.state.monitors || []).find((candidate) => candidate.id === arg);
  if (!monitor || !monitor.camera_id) return;
  ctx.store.picked = monitor.camera_id;
  ctx.float(true);
});

plugin.render((ctx) => ({ type: "camera", camera_id: ctx.store.picked }));
