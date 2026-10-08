import { expect, test, type Page } from "@playwright/test";

const README = "https://raw.githubusercontent.com/o/r/abc/plugin/README.md";

async function rendered(page: Page, markdown: string, options: Record<string, unknown> = {}) {
  await page.goto("/");
  return page.evaluate(
    async ({ markdown, options }) => {
      const path = "/src/markdown.ts";
      const { renderMarkdown } = await import(/* @vite-ignore */ path);
      const box = document.createElement("template");
      box.innerHTML = renderMarkdown(markdown, options);
      return {
        html: box.innerHTML,
        tags: [...new Set([...box.content.querySelectorAll("*")].map((element) => element.localName))].sort(),
        attributes: [
          ...new Set([...box.content.querySelectorAll("*")].flatMap((element) => element.getAttributeNames())),
        ].sort(),
      };
    },
    { markdown, options },
  );
}

test("a README keeps what Markdown writes", async ({ page }) => {
  const { tags, attributes, html } = await rendered(
    page,
    [
      "# Title",
      "## Section",
      "- one\n- two",
      "3. three\n4. four",
      "| a | b |\n|:-:|--:|\n| 1 | 2 |",
      "```js\nlet x;\n```",
      "> quoted",
      "~~gone~~ **bold** *soft* `code`  \nbroken",
      "---",
      '![shot](shot.png "A shot") [link](https://example.com "A link")',
    ].join("\n\n"),
  );
  expect(tags).toEqual([
    "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "hr", "img", "li", "ol", "p", "pre", "strong",
    "table", "tbody", "td", "th", "thead", "tr", "ul",
  ]);
  expect(attributes).toEqual(["align", "alt", "href", "loading", "rel", "src", "start", "target", "title"]);
  expect(html).toContain('<th align="center">a</th>');
  expect(html).toContain('<ol start="3">');
});

test("a README cannot bring forms, media, overlays or the app's own classes", async ({ page }) => {
  const { tags, attributes, html } = await rendered(
    page,
    [
      '<form action="/api/prints" method="post"><input name="file"><button>Send</button></form>',
      '<form method="dialog"><button>Close</button></form>',
      "<audio autoplay src=https://example.com/a.mp3></audio><video src=https://example.com/v.mp4></video>",
      '<div style="position:fixed;inset:0" class="panel" id="root" data-x="1" aria-hidden="true">over</div>',
      "<details open><summary>more</summary></details><dialog open>hello</dialog>",
      "<style>body{display:none}</style><iframe src=https://example.com></iframe>",
      '<img src="shot.png" srcset="https://example.com/x.png 2x" onerror="alert(1)">',
      "<math><mi>x</mi></math>",
      "- [x] done",
    ].join("\n\n"),
  );
  expect(tags.filter((tag) => !["p", "img", "ul", "li"].includes(tag))).toEqual([]);
  expect(attributes).toEqual(["loading", "src"]);
  expect(html).toContain("over");
});

test("an SVG link in a README renders as text", async ({ page }) => {
  const { tags, html } = await rendered(page, '<svg><a href="https://example.com"><text>drawn</text></a></svg>\n\nafter', {
    base: README,
  });
  expect(tags).toEqual(["p"]);
  expect(html).toContain("after");
});

test("a README's images and links resolve against its repository", async ({ page }) => {
  const { html } = await rendered(page, "![shot](docs/shot.png) [guide](docs/guide.md) [site](https://example.com/)", {
    base: README,
  });
  expect(html).toContain('src="https://raw.githubusercontent.com/o/r/abc/plugin/docs/shot.png"');
  expect(html).toContain('href="https://raw.githubusercontent.com/o/r/abc/plugin/docs/guide.md"');
  expect(html).toContain('<a href="https://example.com/" target="_blank" rel="noreferrer">site</a>');
});

test("a plugin README draws pictures from its own repository and from nowhere else", async ({ page }) => {
  const { html } = await rendered(
    page,
    [
      "![own](docs/shot.png) ![up](../shared.png) ![inline](data:image/gif;base64,R0lGODlhAQABAAAAACw=)",
      "![tracker](https://tracker.example/pixel.gif) ![probe](http://192.168.1.1/logo.png) ![scheme-less](//tracker.example/p.gif)",
      "![other repo](https://raw.githubusercontent.com/x/y/abc/shot.png)",
    ].join("\n\n"),
    { base: README, imagePrefixes: ["https://raw.githubusercontent.com/o/r/abc/"] },
  );
  expect([...html.matchAll(/src="([^"]*)"/g)].map((match) => match[1])).toEqual([
    "https://raw.githubusercontent.com/o/r/abc/plugin/docs/shot.png",
    "https://raw.githubusercontent.com/o/r/abc/shared.png",
    "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
  ]);
});

test("an imported plugin README draws only the pictures it carries", async ({ page }) => {
  const { html } = await rendered(page, "![carried](shot.png) ![away](https://tracker.example/p.gif) ![hub](/api/v1/state)", {
    sources: { "shot.png": "data:image/png;base64,AAAA" },
    imagePrefixes: [],
  });
  expect([...html.matchAll(/src="([^"]*)"/g)].map((match) => match[1])).toEqual(["data:image/png;base64,AAAA"]);
});

test("a README picture named after an Object property is not a carried one", async ({ page }) => {
  const names = ["constructor", "toString", "__proto__", "hasOwnProperty"];
  const markdown = names.map((name) => `![x](${name})`).join(" ");
  const carried = { sources: { "shot.png": "data:image/png;base64,AAAA" }, imagePrefixes: [] };
  const withMedia = await rendered(page, markdown, { ...carried, skip: ["shot.png"] });
  const withoutMedia = await rendered(page, markdown, { sources: {}, imagePrefixes: [] });
  expect(withMedia.html).not.toContain("<img");
  expect(withoutMedia.html).not.toContain("<img");
});

test("release notes open their relative links on GitHub at that release", async ({ page }) => {
  const release = {
    version: "2.5.1",
    name: "2.5.1",
    notes: "| Fixed | Where |\n|---|---|\n| `Host` | [Host and origin checking](docs/deployment.md#host-and-origin-checking) |",
    url: "https://github.com/o/r/releases/tag/v2.5.1",
    files_url: "https://github.com/o/r/blob/v2.5.1/",
    published_at: null,
  };
  const engine = {
    event: "state", version: "2.5.1", update: null, cameras: [], printers: [], prints: [], reviews: [], monitors: [],
    tokens: [], notifiers: [], integrations: [],
    settings: { notifiers: {}, update_check: true, theme: "dark", themes: [], layout: {}, preheat: [] },
    stats: { inference_device: "CPU", infer_ms: 1, capacity_fps: 1 },
    plugins: [], plugin_permissions: [], plugin_events: {}, plugin_assets: {},
  };
  await page.addInitScript(() => localStorage.setItem("pg.intro.seen", "1"));
  await page.routeWebSocket(/\/api\/ws$/, (socket) => {
    socket.onMessage((message) => {
      if (JSON.parse(String(message)).cmd === "update.releases")
        socket.send(JSON.stringify({ event: "releases", releases: [release] }));
    });
    socket.send(JSON.stringify(engine));
  });
  await page.goto("/");
  await page.waitForFunction(() => (window as any).__pg?.getState().phase === "ready");
  await page.evaluate(() => (window as any).__pg.getState().openDialog("update"));
  const notes = page.locator(".changelog");
  await expect(notes.getByRole("link", { name: "Host and origin checking" })).toHaveAttribute(
    "href",
    "https://github.com/o/r/blob/v2.5.1/docs/deployment.md#host-and-origin-checking",
  );
  await expect(notes.getByRole("cell", { name: "Host", exact: true }).locator("code")).toBeVisible();
});
