/*
 * PrintGuard plugin sandbox.
 *
 * Runs one plugin file inside an opaque origin with a content security policy
 * that permits no network, no images, no styles and no frames of its own. It
 * is a classic script with no imports on purpose: a module script is always
 * fetched in CORS mode, which an opaque origin can never satisfy, so this file
 * would load and silently run nothing.
 *
 * The plugin is a pure function. It is handed state and its own stored data,
 * and hands back a view and a list of effects for PrintGuard to carry out,
 * every one of which is checked against the permissions the user granted
 * before anything happens.
 */
(function () {
  "use strict";

  for (const name of ["fetch", "XMLHttpRequest", "WebSocket", "EventSource", "Worker", "SharedWorker", "indexedDB", "caches", "importScripts"]) {
    try {
      delete window[name];
    } catch {
      /* frozen on some engines; the policy above is what actually closes these */
    }
  }
  try {
    delete navigator.sendBeacon;
  } catch {
    /* as above */
  }

  let hooks = null;
  let effects = [];
  let store = {};
  let manifest = {};

  function makeContext(state) {
    return {
      store,
      state,
      manifest,
      now: Date.now() / 1000,
      command(cmd) {
        effects.push({ kind: "command", cmd });
      },
      http(request) {
        effects.push({ kind: "http", request });
      },
      notify(text) {
        effects.push({ kind: "notify", text: String(text) });
      },
      log(text) {
        effects.push({ kind: "log", text: String(text) });
      },
    };
  }

  function load(code) {
    const api = {
      render(fn) {
        hooks.view = fn;
      },
      action(fn) {
        hooks.action = fn;
      },
      on(name, fn) {
        hooks.events[name] = fn;
      },
    };
    hooks = { view: null, action: null, events: {} };
    new Function("plugin", code)(api);
  }

  function run(message) {
    const ctx = makeContext(message.state || {});
    effects = [];
    let tree = null;
    if (message.t === "action" && hooks.action) hooks.action(message.name, message.arg, ctx);
    else if (message.t === "event" && hooks.events[message.event.event]) hooks.events[message.event.event](message.event, ctx);
    if (hooks.view) tree = hooks.view(ctx);
    store = ctx.store;
    return { tree, store, effects };
  }

  addEventListener("message", (message) => {
    const { id, t } = message.data || {};
    try {
      if (t === "init") {
        store = message.data.store || {};
        manifest = message.data.manifest || {};
        load(message.data.code);
        parent.postMessage({ id, t: "ready" }, "*");
        return;
      }
      parent.postMessage({ id, t: "result", ...run(message.data) }, "*");
    } catch (err) {
      parent.postMessage({ id, t: "failed", message: String((err && err.message) || err) }, "*");
    }
  });

  parent.postMessage({ t: "booted" }, "*");
})();
