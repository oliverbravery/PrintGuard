const DEFAULT_MINUTES = 30;

plugin.on("result", (event, ctx) => {
  if (event.prediction !== "failure") return;
  const counts = ctx.store.counts || {};
  const seen = counts[event.monitor_id] || { alerts: 0, frames: 0 };
  seen.frames += 1;
  counts[event.monitor_id] = seen;
  ctx.store.counts = counts;
});

plugin.on("alert", (event, ctx) => {
  const counts = ctx.store.counts || {};
  const seen = counts[event.monitor_id] || { alerts: 0, frames: 0 };
  seen.alerts += 1;
  counts[event.monitor_id] = seen;
  ctx.store.counts = counts;
});

plugin.on("tick", (event, ctx) => {
  const on = ctx.store.on || {};
  const every = ctx.store.every || {};
  const counts = ctx.store.counts || {};
  const sent = ctx.store.sent || {};
  const jobs = ctx.store.jobs || {};
  const now = Date.now();

  for (const monitor of ctx.state.monitors || []) {
    const printer = (ctx.state.printers || []).find((candidate) => candidate.id === monitor.printer_id);
    const device = printer ? printer.device_state : null;
    const job = device ? device.job : null;
    if (jobs[monitor.id] !== job) {
      if (monitor.id in jobs) counts[monitor.id] = { alerts: 0, frames: 0 };
      jobs[monitor.id] = job;
      sent[monitor.id] = now;
    }
    if (on[monitor.id] !== true) continue;
    if (now - (sent[monitor.id] || 0) < (every[monitor.id] || DEFAULT_MINUTES) * 60000) continue;
    sent[monitor.id] = now;
    const seen = counts[monitor.id] || { alerts: 0, frames: 0 };
    const how = device && device.status === "printing" ? Math.round(device.progress) + "% done" : "not printing";
    ctx.command({
      cmd: "notify.send",
      title: monitor.name + ", " + how,
      text: seen.alerts + " alerts and " + seen.frames + " frames over " + monitor.threshold + " this print",
    });
  }

  ctx.store.counts = counts;
  ctx.store.sent = sent;
  ctx.store.jobs = jobs;
});
