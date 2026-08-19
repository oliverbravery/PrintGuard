plugin.render((ctx) => {
  const monitor = (ctx.state.monitors || []).find((candidate) => candidate.id === ctx.target);
  if (!monitor || !monitor.camera_id) return null;
  return { type: "float", label: "Float " + monitor.name, camera_id: monitor.camera_id };
});
