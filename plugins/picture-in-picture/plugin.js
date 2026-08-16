plugin.action((name, arg, ctx) => {
  if (name !== "toggle") return;
  const picked = ctx.store.picked || [];
  ctx.store.picked = picked.includes(arg) ? picked.filter((id) => id !== arg) : [...picked, arg];
});

plugin.render((ctx) => {
  const cameras = ctx.state.cameras || [];
  const picked = (ctx.store.picked || []).filter((id) => cameras.some((camera) => camera.id === id));
  const chosen = picked.length ? picked : cameras.slice(0, 1).map((camera) => camera.id);

  return {
    type: "col",
    children: [
      {
        type: "row",
        children: cameras.map((camera) => ({
          type: "button",
          label: (chosen.includes(camera.id) ? "● " : "○ ") + camera.name,
          action: "toggle",
          arg: camera.id,
        })),
      },
      ...(cameras.length
        ? chosen.map((id) => ({ type: "camera", camera_id: id }))
        : [{ type: "text", value: "Add a camera to see it here.", muted: true }]),
    ],
  };
});
