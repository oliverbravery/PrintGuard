// The whole plugin. Its manifest takes the monitor surface, so PrintGuard calls
// render once per monitor with ctx.target naming which, and draws what comes back
// on that monitor's tile.
plugin.render((ctx) => {
  // ctx.state holds only what the granted permissions allow, refreshed for every
  // call, and state:read is the one that puts monitors in it.
  const monitor = (ctx.state.monitors || []).find((candidate) => candidate.id === ctx.target);
  // Returning null draws nothing, which is how a plugin sits out a monitor it has
  // nothing to offer.
  if (!monitor || !monitor.camera_id) return null;
  // A float node needs camera:view. PrintGuard floats the camera from the press
  // itself rather than from anything returned here, since a browser only floats a
  // video for something the user did.
  return { type: "float", label: "Float " + monitor.name, camera_id: monitor.camera_id };
});
