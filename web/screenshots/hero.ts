import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  siBambulab,
  siDiscord,
  siElegoo,
  siHomeassistant,
  siNtfy,
  siOctoprint,
  siTelegram,
  type SimpleIcon,
} from "simple-icons";

const here = dirname(fileURLToPath(import.meta.url));

interface Logo {
  name: string;
  svg: string;
  size?: number;
}

const mark = (icon: SimpleIcon, fill = `#${icon.hex}`): string =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="${icon.path}" fill="${fill}"/></svg>`;

const file = (name: string, recolour: Record<string, string> = {}): string =>
  Object.entries(recolour).reduce(
    (svg, [from, to]) => svg.replaceAll(from, to),
    readFileSync(resolve(here, "logos", name), "utf8"),
  );

const PRINTERS: Logo[] = [
  { name: "OctoPrint", svg: mark(siOctoprint) },
  { name: "Klipper", svg: file("klipper.svg", { "#3c4b5a": "#8ba1b5" }), size: 54 },
  { name: "Elegoo", svg: mark(siElegoo, "#8093e8") },
  { name: "Prusa", svg: file("prusa.svg"), size: 58 },
  { name: "Bambu Lab", svg: mark(siBambulab) },
];

const ALERTS: Logo[] = [
  { name: "ntfy", svg: mark(siNtfy, "#46a793") },
  { name: "Telegram", svg: mark(siTelegram) },
  { name: "Discord", svg: mark(siDiscord) },
  { name: "Home Assistant", svg: mark(siHomeassistant) },
];

const chips = (logos: Logo[], side: 1 | -1): string =>
  logos
    .map((logo, i) => {
      const arc = side * Math.round(38 * Math.sin((Math.PI * i) / (logos.length - 1)));
      const size = logo.size ?? 42;
      const svg = logo.svg.replace("<svg ", `<svg style="width:${size}px;height:${size}px" `);
      return `<div class="chipwrap" style="transform:translateX(${arc}px)">
        <div class="chip">${svg}</div>
        <div class="chipname">${logo.name}</div>
      </div>`;
    })
    .join("\n");

export function heroHtml(dashboard: string, drawer: string): string {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@600&family=Chivo+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { width: 1600px; height: 800px; background: transparent; }
  .hero {
    position: relative;
    width: 100%;
    height: 100%;
    border-radius: 28px;
    overflow: hidden;
    border: 1px solid #262b20;
    background:
      radial-gradient(640px 420px at 50% 14%, rgb(255 77 0 / 0.13), transparent 70%),
      radial-gradient(900px 480px at 50% 120%, rgb(255 77 0 / 0.06), transparent 70%),
      repeating-linear-gradient(0deg, rgb(236 238 230 / 0.022) 0 1px, transparent 1px 48px),
      repeating-linear-gradient(90deg, rgb(236 238 230 / 0.022) 0 1px, transparent 1px 48px),
      #0b0c0a;
  }
  .beam {
    position: absolute;
    left: 110px;
    right: 110px;
    top: 399px;
    height: 1px;
    z-index: 1;
    background: linear-gradient(90deg, transparent, rgb(255 77 0 / 0.4) 16%, rgb(255 77 0 / 0.4) 84%, transparent);
  }
  .collabel {
    position: absolute;
    top: 88px;
    width: 170px;
    text-align: center;
    z-index: 4;
    font-family: "Saira Condensed", "Arial Narrow", sans-serif;
    font-weight: 600;
    font-size: 15px;
    letter-spacing: 0.24em;
    text-transform: uppercase;
    color: #7e866d;
  }
  .col {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    z-index: 4;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
    width: 170px;
  }
  .chipwrap { display: flex; flex-direction: column; align-items: center; gap: 7px; }
  .chip {
    width: 78px;
    height: 78px;
    border-radius: 20px;
    background: #181b13;
    border: 1px solid #262b20;
    display: grid;
    place-items: center;
    box-shadow: 0 6px 18px rgb(0 0 0 / 0.4);
  }
  .chipname {
    font-family: "Chivo Mono", ui-monospace, monospace;
    font-size: 13px;
    letter-spacing: 0.04em;
    color: #a8af9c;
    white-space: nowrap;
  }
  .shot {
    position: absolute;
    border-radius: 14px;
    border: 1px solid rgb(236 238 230 / 0.16);
    overflow: hidden;
    background: #0b0c0a;
    box-shadow: 0 30px 70px rgb(0 0 0 / 0.62);
  }
  .shot img { display: block; width: 100%; height: auto; }
</style>
</head>
<body>
<div class="hero">
  <div class="beam"></div>
  <div class="collabel" style="left:70px">Print services</div>
  <div class="collabel" style="right:70px">Alerts</div>
  <div class="col" style="left:70px">
    ${chips(PRINTERS, 1)}
  </div>
  <div class="col" style="right:70px">
    ${chips(ALERTS, -1)}
  </div>
  <div class="shot" style="left:1056px;top:292px;width:270px;z-index:2">
    <img src="data:image/png;base64,${drawer}" alt="">
  </div>
  <div class="shot" style="left:264px;top:108px;width:810px;z-index:3">
    <img src="data:image/png;base64,${dashboard}" alt="">
  </div>
</div>
</body>
</html>`;
}
