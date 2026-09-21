import { useState } from "react";
import { Wordmark } from "../src/components/Wordmark";
import dashboardDark from "../../docs/assets/dashboard.png";
import dashboardLight from "../../docs/assets/dashboard-light.png";
import printerDetail from "../../docs/assets/printer-detail.png";
import printViewer from "../../docs/assets/print-viewer.png";
import pluginsLive from "../../docs/assets/plugins-live.png";
import customise from "../../docs/assets/customise.png";

const REPO_URL = "https://github.com/oliverbravery/PrintGuard";
const MODEL_URL = "https://github.com/oliverbravery/Edge-FDM-Fault-Detection";
const DOCS_URL = `${REPO_URL}/blob/main/docs`;
const DOWNLOAD = `${REPO_URL}/releases/latest/download`;
const MAC_DOWNLOAD = `${DOWNLOAD}/PrintGuard-macos-arm64.dmg`;
const WIN_DOWNLOAD = `${DOWNLOAD}/PrintGuard-windows-x64.zip`;
const UNRAID_URL = `${REPO_URL}/blob/main/templates/printguard.xml`;
const ACCELERATION_URL = `${DOCS_URL}/hardware.md`;

const DOCS: { title: string; page: string; body: string }[] = [
  { title: "Printers & cameras", page: "printers.md", body: "Connect OctoPrint, Klipper, Elegoo, Prusa or Bambu Lab, add cameras and set up alert channels." },
  { title: "Hardware", page: "hardware.md", body: "Pick an image variant and use an Intel or NVIDIA GPU, or an NPU." },
  { title: "Deployment", page: "deployment.md", body: "Reach your hub from outside your network without exposing it." },
  { title: "API & MCP", page: "api.md", body: "Drive the hub from a script, an agent or Home Assistant." },
  { title: "Plugins", page: "plugins.md", body: "Install a plugin, see what it can reach, or write your own." },
  { title: "Troubleshooting", page: "troubleshooting.md", body: "Fix a dead feed, a failing printer test or a port already in use." },
];

const DOCKER_CMD = `docker run -d --name printguard --restart unless-stopped \\
  -p 8000:8000 -p 8554:8554 \\
  -v printguard:/data \\
  ghcr.io/oliverbravery/printguard`;
const COMPOSE_CMD =
  "curl -fsSLO https://raw.githubusercontent.com/oliverbravery/PrintGuard/main/docker-compose.yaml && docker compose up -d";

function detectOS(): "mac" | "windows" | "other" {
  if (/iPhone|iPad|Android/i.test(navigator.userAgent)) return "other";
  if (/Mac/i.test(navigator.userAgent)) return navigator.maxTouchPoints > 1 ? "other" : "mac";
  if (/Win/i.test(navigator.userAgent)) return "windows";
  return "other";
}

function scrollToId(id: string) {
  return (event: React.MouseEvent) => {
    event.preventDefault();
    document.getElementById(id)?.scrollIntoView({ block: "start" });
  };
}

function AppleIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" aria-hidden="true">
      <path d="M16.365 1.43c0 1.14-.42 2.21-1.12 3.01-.78.9-2.06 1.6-3.18 1.51-.14-1.11.42-2.27 1.07-3 .73-.82 2.03-1.45 3.23-1.52zM20.5 17.2c-.55 1.27-.82 1.84-1.53 2.97-.99 1.57-2.39 3.53-4.12 3.54-1.54.02-1.94-1-4.03-.99-2.09.01-2.53 1.01-4.07.99-1.73-.02-3.05-1.78-4.04-3.35C-.07 16.5-.3 11.2 1.94 8.45c1.05-1.31 2.69-2.13 4.24-2.13 1.58 0 2.57 1 4.03 1 1.42 0 2.28-1 4.11-1 1.38 0 2.84.75 3.88 2.05-3.41 1.87-2.85 6.74.3 8.83z" />
    </svg>
  );
}

function WindowsIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" aria-hidden="true">
      <path d="M3 3h8v8H3zM13 3h8v8h-8zM3 13h8v8H3zM13 13h8v8h-8z" />
    </svg>
  );
}

function DownloadButton({ label, href, icon, primary }: { label: string; href: string; icon: React.ReactNode; primary?: boolean }) {
  const tone = primary ? "border-accent text-accent" : "text-text-1 hover:border-accent group-hover:text-accent";
  return (
    <a className={`panel group inline-flex items-center gap-2.5 px-5 py-3 transition-colors ${primary ? "border-accent" : "hover:border-accent"}`} href={href} target="_blank" rel="noreferrer">
      <span className={`${primary ? "text-accent" : "text-text-1 group-hover:text-accent"} transition-colors`}>{icon}</span>
      <span className={`display text-sm tracking-[0.08em] transition-colors ${tone}`}>Download {label}</span>
    </a>
  );
}

function Command({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="panel relative min-w-0">
      <pre className="mono overflow-x-auto px-4 py-3 pr-16 text-[0.72rem] leading-relaxed text-text-1">{command}</pre>
      <button className="btn absolute right-2.5 top-2.5 px-2 py-1" onClick={copy} aria-label="Copy command">
        {copied ? "copied" : "copy"}
      </button>
    </div>
  );
}

function Spec({ value, label, index }: { value: string; label: string; index: number }) {
  return (
    <div className="reveal flex flex-col items-center leading-tight" style={{ "--i": index } as React.CSSProperties}>
      <span className="mono text-sm text-text-0 whitespace-nowrap">{value}</span>
      <span className="label whitespace-nowrap">{label}</span>
    </div>
  );
}

function Feature({ led, title, body, index }: { led: string; title: string; body: string; index: number }) {
  return (
    <div className="panel reveal relative p-5" style={{ "--i": index } as React.CSSProperties}>
      <div className="mb-2 flex items-center gap-2.5">
        <span className={`led ${led}`} />
        <h3 className="display text-sm font-semibold tracking-[0.2em]">{title}</h3>
      </div>
      <p className="text-[0.84rem] leading-relaxed text-text-1">{body}</p>
    </div>
  );
}

function Shot({ src, alt, w, h, eager }: { src: string; alt: string; w: number; h: number; eager?: boolean }) {
  return (
    <div className="panel tile reveal relative overflow-hidden">
      <span className="corner corner-tl" />
      <span className="corner corner-tr" />
      <span className="corner corner-bl" />
      <span className="corner corner-br" />
      <img src={src} alt={alt} width={w} height={h} loading={eager ? undefined : "lazy"} fetchPriority={eager ? "high" : undefined} className="block h-auto w-full" />
    </div>
  );
}

function Showcase({ src, alt, w, h, kicker, title, body, flip }: { src: string; alt: string; w: number; h: number; kicker: string; title: string; body: string; flip?: boolean }) {
  return (
    <div className="grid items-center gap-6 lg:grid-cols-2">
      <div className={flip ? "lg:order-2" : ""}>
        <Shot src={src} alt={alt} w={w} h={h} />
      </div>
      <div className={flip ? "lg:order-1" : ""}>
        <p className="label mb-2 text-accent">{kicker}</p>
        <h3 className="display mb-3 text-2xl font-bold sm:text-3xl">{title}</h3>
        <p className="leading-relaxed text-text-1">{body}</p>
      </div>
    </div>
  );
}

function DocLink({ title, page, body }: { title: string; page: string; body: string }) {
  return (
    <a className="panel group block p-5 transition-colors hover:border-accent" href={`${DOCS_URL}/${page}`} target="_blank" rel="noreferrer">
      <h3 className="display mb-1.5 text-sm font-semibold tracking-[0.14em] transition-colors group-hover:text-accent">{title} ↗</h3>
      <p className="text-[0.84rem] leading-relaxed text-text-1">{body}</p>
    </a>
  );
}

export function Home() {
  const os = detectOS();
  const download = os === "mac" ? { label: "macOS", href: MAC_DOWNLOAD } : os === "windows" ? { label: "Windows", href: WIN_DOWNLOAD } : null;
  const mac = <DownloadButton label="macOS" href={MAC_DOWNLOAD} icon={<AppleIcon />} primary={os === "mac"} />;
  const win = <DownloadButton label="Windows" href={WIN_DOWNLOAD} icon={<WindowsIcon />} primary={os === "windows"} />;

  return (
    <div className="min-h-screen">
      <nav className="sticky top-0 z-40 border-b border-line-0 bg-ink-0/85 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-5 py-3">
          <Wordmark />
          <div className="flex-1" />
          <a className="mono hidden text-[0.66rem] text-text-2 transition-colors hover:text-accent sm:inline" href="#features" onClick={scrollToId("features")}>FEATURES</a>
          <a className="mono hidden text-[0.66rem] text-text-2 transition-colors hover:text-accent sm:inline" href="#docs" onClick={scrollToId("docs")}>DOCS</a>
          <a className="mono hidden whitespace-nowrap text-[0.66rem] text-text-2 transition-colors hover:text-accent min-[400px]:inline" href={REPO_URL} target="_blank" rel="noreferrer">GITHUB ↗</a>
          <a className="btn btn-primary" href="#install" onClick={scrollToId("install")}>Install</a>
        </div>
      </nav>

      <section className="mx-auto max-w-4xl px-5 pb-12 pt-16 text-center sm:pt-24">
        <p className="mono reveal mb-6 text-[0.65rem] tracking-[0.32em] text-text-2">FDM FAILURE DETECTION · SELF-HOSTED</p>
        <h1 className="display reveal mb-6 text-[2.7rem] font-bold leading-[0.95] sm:text-7xl" style={{ "--i": 1 } as React.CSSProperties}>
          EVERY LAYER WATCHED.
          <br />
          <span className="text-accent">EVERY FAILURE CAUGHT.</span>
        </h1>
        <p className="reveal mx-auto mb-8 max-w-2xl text-[0.95rem] text-text-1 sm:text-lg" style={{ "--i": 2 } as React.CSSProperties}>
          PrintGuard watches your printer cameras with an on-device vision model, pauses the printer through
          OctoPrint, Klipper, Elegoo, Prusa or Bambu Lab when a defect holds, and pushes a snapshot to your phone. No
          cloud and no subscription, so your frames stay yours.
        </p>
        <div className="reveal flex flex-wrap items-center justify-center gap-3" style={{ "--i": 3 } as React.CSSProperties}>
          {download && <a className="btn btn-primary" href={download.href}>Download for {download.label}</a>}
          <a className={`btn ${download ? "" : "btn-primary"}`} href="#install" onClick={scrollToId("install")}>Run it in Docker</a>
        </div>
        <div className="mt-10 grid grid-cols-2 gap-x-6 gap-y-4 sm:flex sm:items-center sm:justify-center sm:gap-12">
          <Spec index={3} value="≈5 MB" label="model" />
          <Spec index={4} value="0" label="frames to cloud" />
          <Spec index={5} value="5" label="printer services" />
          <Spec index={6} value="GPL-2.0" label="licence" />
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 pb-20">
        <Shot src={dashboardDark} alt="PrintGuard dashboard: three cameras at a glance, one print mid-failure and auto-paused" w={1360} h={620} eager />
      </section>

      <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-5 pb-20">
        <p className="label mb-8 text-center">WHAT IT DOES</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Feature index={2} led="led-infer" title="Detect" body="A compact encoder scores every frame against failure prototypes, scheduled fairly across all your cameras." />
          <Feature index={3} led="led-on" title="Act" body="A sustained defect pauses or cancels the print through OctoPrint, Klipper, Elegoo, Prusa or Bambu, and inference rests while the printer is idle." />
          <Feature index={4} led="led-bad" title="Alert" body="The moment a defect holds, PrintGuard sends a snapshot to your phone over ntfy, Pushover, Telegram or Discord." />
          <Feature index={5} led="led-warn" title="Fail safe" body="A watchdog warns the second a camera drops, a feed freezes or your printer stops answering. Nothing fails silently." />
        </div>
      </section>

      <section className="mx-auto max-w-6xl space-y-16 px-5 pb-20">
        <Showcase src={printerDetail} alt="Monitor detail with live risk score and printer controls" w={1360} h={860} kicker="EVERY MONITOR, IN DEPTH" title="Open any monitor" body="Live risk score, score history, temperatures and one-tap pause, resume or cancel, bound to the printer through your print server." />
        <Showcase flip src={printViewer} alt="A sliced file in the 3D viewer, with its print time, filament and temperatures" w={1360} h={860} kicker="PRINT LIBRARY" title="Send a print from the dashboard" body="Drop sliced files onto the hub to preview the toolpath layer by layer and check the print time, filament and temperatures. Send one to an idle printer when you're ready." />
        <Showcase src={pluginsLive} alt="The dashboard with the Spotify plugin's panel and album cover behind it" w={1360} h={720} kicker="PLUGINS" title="Add what you need" body="Plugins are written in JavaScript and run in a sandbox with only the permissions you grant. Install verified plugins from the in-app plugin store or install them from GitHub repos or zips." />
        <Showcase flip src={customise} alt="Customise mode: drag to reorder, pin and hide monitors and cameras" w={1360} h={860} kicker="YOUR DASHBOARD, YOUR WAY" title="Arrange it around your workflow" body="Drag monitors into any order, pin the ones that matter to the front and hide the rest. The camera rail rearranges the same way, with mouse, touch or keyboard." />
        <Showcase src={dashboardLight} alt="PrintGuard in its light theme" w={1360} h={620} kicker="MAKE IT YOURS" title="Light, dark, or a theme you design" body="Pick System, Light or Dark from the header, or build your own in the theme editor, saved and synced to every browser that opens the hub." />
      </section>

      <section id="install" className="mx-auto max-w-6xl scroll-mt-20 px-5 pb-20">
        <p className="label mb-2 text-center">INSTALL</p>
        <h2 className="display mb-10 text-center text-3xl font-bold sm:text-4xl">Run it your way</h2>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="panel relative min-w-0 p-6 sm:p-7">
            <span className="corner corner-tl" />
            <span className="corner corner-tr" />
            <span className="corner corner-bl" />
            <span className="corner corner-br" />
            <p className="label mb-1 text-accent">DESKTOP APP</p>
            <h3 className="display mb-2 text-2xl font-bold">macOS &amp; Windows</h3>
            <p className="mb-5 text-sm leading-relaxed text-text-1">
              A native app with no Docker and no terminal. It runs the hub in its own window and keeps watching while
              minimised. Reach it from your phone on the same network too.
            </p>
            <div className="flex flex-wrap gap-3">
              {os === "windows" ? (
                <>
                  {win}
                  {mac}
                </>
              ) : (
                <>
                  {mac}
                  {win}
                </>
              )}
            </div>
            <p className="mt-4 text-xs leading-relaxed text-text-2">
              The Windows build is unsigned for now, so its first launch needs a one-time approval. Choose{" "}
              <span className="text-text-1">More info</span>, then <span className="text-text-1">Run anyway</span>.
            </p>
          </div>

          <div className="panel relative min-w-0 p-6 sm:p-7">
            <span className="corner corner-tl" />
            <span className="corner corner-tr" />
            <span className="corner corner-bl" />
            <span className="corner corner-br" />
            <p className="label mb-1 text-accent">SELF-HOST</p>
            <h3 className="display mb-2 text-2xl font-bold">Docker, for a server or NAS</h3>
            <p className="mb-4 text-sm leading-relaxed text-text-1">
              One container on port 8000, dashboard and live video included. Images for amd64 and arm64 (Raspberry Pi).
            </p>
            <Command command={DOCKER_CMD} />
            <p className="mb-2 mt-5 text-xs text-text-2">OR WITH COMPOSE</p>
            <Command command={COMPOSE_CMD} />
            <p className="mt-4 text-xs leading-relaxed text-text-2">
              Inference runs on the CPU out of the box. An Intel GPU or NPU needs only{" "}
              <span className="text-text-1">--device /dev/dri</span>; an NVIDIA RTX 30 series or newer host uses the{" "}
              <span className="text-text-1">:latest-nvidia</span> image with{" "}
              <span className="text-text-1">--gpus all</span>.{" "}
              <a className="text-text-1 underline decoration-line-0 underline-offset-2 transition-colors hover:text-accent" href={ACCELERATION_URL} target="_blank" rel="noreferrer">
                Hardware acceleration ↗
              </a>
            </p>
            <a className="mono mt-4 inline-block text-[0.7rem] text-text-2 transition-colors hover:text-accent" href={UNRAID_URL} target="_blank" rel="noreferrer">
              Unraid, install from Community Applications ↗
            </a>
          </div>
        </div>
      </section>

      <section id="docs" className="mx-auto max-w-6xl scroll-mt-20 px-5 pb-24">
        <p className="label mb-2 text-center">DOCUMENTATION</p>
        <h2 className="display mb-10 text-center text-3xl font-bold sm:text-4xl">Where to go next</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {DOCS.map((doc) => (
            <DocLink key={doc.page} {...doc} />
          ))}
        </div>
      </section>

      <footer className="hairline flex flex-wrap items-center justify-center gap-x-7 gap-y-2 px-6 py-6">
        <a className="mono text-[0.66rem] text-text-2 transition-colors hover:text-accent" href={REPO_URL} target="_blank" rel="noreferrer">
          github.com/oliverbravery/PrintGuard
        </a>
        <a className="mono text-[0.66rem] text-text-2 transition-colors hover:text-accent" href={MODEL_URL} target="_blank" rel="noreferrer">
          model: Edge-FDM-Fault-Detection
        </a>
      </footer>
    </div>
  );
}
