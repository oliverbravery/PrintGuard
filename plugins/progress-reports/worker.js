// The worker half. It has no UI and gets a fresh VM every time it wakes, so
// anything it needs to remember goes in ctx.store, which is the same store the
// panel in plugin.js reads and writes.
const DEFAULT_MINUTES = 30;

// result fires on every inference on a watched monitor, before any threshold or
// streak logic, so this counts raw frames the model called a failure. An event
// only fires if the manifest names it in events.
plugin.on("result", (event, ctx) => {
  if (event.prediction !== "failure") return;
  const counts = ctx.store.counts || {};
  const seen = counts[event.monitor_id] || { alerts: 0, frames: 0 };
  seen.frames += 1;
  counts[event.monitor_id] = seen;
  ctx.store.counts = counts;
});

// alert fires once a defect has held long enough for PrintGuard to act on it, so
// there are far fewer of these than there are results.
plugin.on("alert", (event, ctx) => {
  const counts = ctx.store.counts || {};
  const seen = counts[event.monitor_id] || { alerts: 0, frames: 0 };
  seen.alerts += 1;
  counts[event.monitor_id] = seen;
  ctx.store.counts = counts;
});

// tick is the worker's own timer, running as often as tick_s in the manifest asks.
// Waking every minute and deciding here what is due beats one timer per monitor,
// since every monitor can be on a different interval.
plugin.on("tick", (event, ctx) => {
  const on = ctx.store.on || {};
  const every = ctx.store.every || {};
  const counts = ctx.store.counts || {};
  const sent = ctx.store.sent || {};
  const jobs = ctx.store.jobs || {};
  const now = Date.now();

  for (const monitor of ctx.state.monitors || []) {
    const printer = (ctx.state.printers || []).find((candidate) => candidate.id === monitor.printer_id);
    // device_state is null until the printer has been polled once, and a monitor
    // need not have a printer at all.
    const device = printer ? printer.device_state : null;
    const job = device ? device.job : null;
    // A new job starts the tally and the clock again, so a report covers this
    // print rather than everything since the plugin was installed.
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
    // notify.send is an engine command rather than something the plugin does
    // itself, so this goes out through whichever alert channels the user set up.
    // It needs alert:send, and a command the plugin was not granted is refused.
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
