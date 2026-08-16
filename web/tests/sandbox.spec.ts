import { expect, test } from "@playwright/test";

const PROBE = `
plugin.render((ctx) => ({
  type: "col",
  children: [
    { type: "text", value: "origin:" + String(window.origin) },
    { type: "text", value: "fetch:" + typeof fetch },
    { type: "text", value: "socket:" + typeof WebSocket },
    { type: "text", value: "storage:" + (() => { try { return typeof localStorage; } catch { return "blocked"; } })() },
    { type: "text", value: "parent:" + (() => { try { return String(parent.document.title); } catch { return "blocked"; } })() },
    { type: "text", value: "monitors:" + (ctx.state.monitors || []).length },
  ],
}));
`;

async function runInSandbox(page: import("@playwright/test").Page, code: string, state: unknown = {}) {
  return page.evaluate(
    ([code, state]) =>
      new Promise<any>((resolve, reject) => {
        const frame = document.createElement("iframe");
        frame.src = "plugin-sandbox.html";
        frame.sandbox.add("allow-scripts");
        frame.allow = "";
        const answer = (event: MessageEvent) => {
          if (event.source !== frame.contentWindow) return;
          if (event.data.t === "booted") {
            frame.contentWindow!.postMessage({ id: 1, t: "init", code, store: {}, manifest: {} }, "*");
          } else if (event.data.t === "ready") {
            frame.contentWindow!.postMessage({ id: 2, t: "state", state }, "*");
          } else {
            removeEventListener("message", answer);
            resolve(event.data);
          }
        };
        addEventListener("message", answer);
        document.body.appendChild(frame);
        setTimeout(() => reject(new Error("sandbox never answered")), 5000);
      }),
    [code, state] as const,
  );
}

test("a plugin runs in an opaque origin with no way out", async ({ page }) => {
  await page.goto("/");
  const result = await runInSandbox(page, PROBE, { monitors: [{ id: "a" }, { id: "b" }] });
  const said = Object.fromEntries(result.tree.children.map((c: any) => c.value.split(":")));

  expect(said.origin).toBe("null");
  expect(said.fetch).toBe("undefined");
  expect(said.socket).toBe("undefined");
  expect(said.storage).toBe("blocked");
  expect(said.parent).toBe("blocked");
  expect(said.monitors).toBe("2");
});

test("a plugin that throws is reported rather than silently dead", async ({ page }) => {
  await page.goto("/");
  const result = await runInSandbox(page, "plugin.render(() => { throw new Error('boom'); });");

  expect(result.t).toBe("failed");
  expect(result.message).toContain("boom");
});

test("effects come back for the host to check rather than being performed", async ({ page }) => {
  await page.goto("/");
  const result = await runInSandbox(
    page,
    "plugin.render((ctx) => { ctx.command({ cmd: 'printer.action', action: 'cancel' }); return { type: 'text', value: 'hi' }; });",
  );

  expect(result.effects).toEqual([{ kind: "command", cmd: { cmd: "printer.action", action: "cancel" } }]);
});
