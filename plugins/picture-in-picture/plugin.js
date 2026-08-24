// The whole plugin. The monitor surface calls render once per monitor, ctx.target
// naming which, and draws the result on that tile.
plugin.render((ctx) => {
  // ctx.state holds what the grants allow, refreshed every call. state:read is what
  // puts monitors in it.
  const monitor = (ctx.state.monitors || []).find((candidate) => candidate.id === ctx.target);
  // Returning null draws nothing.
  if (!monitor || !monitor.camera_id) return null;
  // A float node needs camera:view. PrintGuard floats from the press itself, since a
  // browser only floats a video for something the user did.
  return { type: "float", label: "Float " + monitor.name, camera_id: monitor.camera_id };
});
