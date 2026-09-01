import type { ReactNode } from "react";
import { BugIcon } from "./components/BugIcon";
import type { DialogKind } from "./store";

const REPO = "https://github.com/oliverbravery/PrintGuard";
const docs = (page: string) => `${REPO}/blob/main/docs/${page}`;
const link = "text-accent underline hover:opacity-80";

export interface GuideSection {
  id: string;
  led: string;
  title: string;
  body: ReactNode;
  shot?: string;
  visual?: ReactNode;
  action?: { label: string; dialog: DialogKind };
  hubOnly?: boolean;
}

const WATCH_STATES: { led: string; when: string; then: string }[] = [
  { led: "led-on", when: "Printing, or no printer linked", then: "Watching, every frame scored" },
  { led: "led-off", when: "Positively idle, paused or errored", then: "Standby, nothing scored" },
  { led: "led-warn", when: "A dropped camera, a frozen feed, or a printer state it cannot read", then: "Keeps watching, and warns you" },
];

export const INTRO: GuideSection[] = [
  {
    id: "what",
    led: "led-infer",
    title: "What PrintGuard does",
    shot: "alert",
    body: (
      <>
        A vision model running on your own hardware scores every frame from your printer camera. When
        a defect holds it pauses or cancels the print and sends you a snapshot. No frame ever leaves
        your network.
      </>
    ),
  },
  {
    id: "sources",
    led: "led-on",
    title: "Cameras and printers",
    shot: "cameras",
    body: (
      <>
        A camera is any video source PrintGuard can read, so a USB device or an RTSP, MJPEG or WebRTC
        stream. A printer is optional, and connecting one lets PrintGuard read whether it is printing
        and stop it when something goes wrong.
      </>
    ),
  },
  {
    id: "monitors",
    led: "led-infer",
    title: "Monitors are what you tune",
    shot: "tuning",
    body: (
      <>
        A monitor binds one camera to one printer and carries the alert threshold, how many detections
        in a row count as a defect, and what happens when one holds. Everything is set per monitor
        from its detail panel.
      </>
    ),
  },
  {
    id: "watching",
    led: "led-warn",
    title: "When inference runs",
    shot: "standby",
    body: (
      <>
        Only a printer that positively reports it is not printing stands a monitor down, so an idle
        printer costs you nothing. Everything else keeps watching.
      </>
    ),
    visual: (
      <ul className="space-y-2">
        {WATCH_STATES.map((state) => (
          <li key={state.led} className="flex gap-3 rounded border border-line-0 bg-ink-0/40 px-3.5 py-2.5">
            <span className={`led ${state.led} mt-[0.4rem]`} />
            <div className="min-w-0">
              <div className="text-sm text-text-0">{state.when}</div>
              <div className="text-xs leading-relaxed text-text-2">{state.then}</div>
            </div>
          </li>
        ))}
      </ul>
    ),
  },
  {
    id: "start",
    led: "led-on",
    title: "Start watching",
    shot: "checklist",
    body: (
      <>
        Register a camera, then add a monitor binding it. Connect a printer and a notification channel
        such as ntfy or Telegram for the full net. The rest of the guide sits behind the ? in the
        header.
      </>
    ),
    action: { label: "Register a camera", dialog: "cameras" },
  },
];

export const GUIDE: GuideSection[] = [
  {
    id: "what",
    led: "led-infer",
    title: "What PrintGuard does",
    body: (
      <>
        PrintGuard watches your printer cameras with an on-device vision model, pauses or cancels the
        print when a defect holds, and pushes a snapshot to your phone. There's no cloud and no subscription,
        your frames never leave hardware you own.
      </>
    ),
  },
  {
    id: "modes",
    led: "led-on",
    title: "Local vs Hub mode",
    body: (
      <>
        <strong>Local</strong> runs the whole engine in this browser tab and uses this device's
        cameras, with nothing to install. <strong>Hub</strong> runs on your own hardware, watches RTSP and
        published streams, and keeps monitoring with every tab closed. Switch any time from the mode
        chip in the header.
      </>
    ),
  },
  {
    id: "cameras",
    led: "led-on",
    title: "Cameras",
    shot: "cameras",
    body: (
      <>
        A camera is any video source PrintGuard can read, so a USB or CSI device, an RTSP, MJPEG or
        WebRTC (WHEP) stream URL, or a camera published from this device. Printers that expose a
        webcam register theirs automatically.
      </>
    ),
    action: { label: "Open cameras", dialog: "cameras" },
  },
  {
    id: "printers",
    led: "led-on",
    title: "Printers",
    shot: "printers",
    body: (
      <>
        Connect a printer, whether <strong>OctoPrint</strong>, <strong>Klipper (Moonraker)</strong>, <strong>Elegoo</strong>,{" "}
        <strong>PrusaLink</strong> or <strong>Bambu Lab</strong>, and PrintGuard can read its status and pause or cancel a print on
        a defect. It's optional: without one, a monitor still watches and alerts.{" "}
        <a className={link} href={docs("printers.md")} target="_blank" rel="noreferrer">
          Setup guides ↗
        </a>
      </>
    ),
    action: { label: "Open printers", dialog: "printers" },
  },
  {
    id: "monitors",
    led: "led-infer",
    title: "Monitors, the core unit",
    shot: "alert",
    body: (
      <>
        A monitor binds one camera (and optionally one printer) and carries the detection thresholds
        and defect response. Inference is shared fairly across every monitor on watch. Its status dot
        is green while watching, grey in standby or offline, and red during a defect alert.
      </>
    ),
    action: { label: "Add a monitor", dialog: "monitor" },
  },
  {
    id: "detection",
    led: "led-warn",
    title: "How detection works",
    shot: "tuning",
    body: (
      <>
        Every frame is scored against failure prototypes. <strong>Alert threshold</strong> sets how
        high that score must reach, <strong>sensitivity</strong> widens or narrows the margin, and a
        defect must hold for a number of <strong>consecutive detections</strong> before PrintGuard
        acts. Tune it all per monitor from its detail panel.
      </>
    ),
  },
  {
    id: "alerts",
    led: "led-bad",
    title: "Alerts",
    shot: "alerts",
    body: (
      <>
        Add a notification channel, whether <strong>ntfy</strong>, <strong>Pushover</strong>,{" "}
        <strong>Telegram</strong>, <strong>Discord</strong>, or <strong>native notifications</strong>{" "}
        in the desktop app, and PrintGuard sends a snapshot the moment a defect holds. Turn
        notifications on per monitor in its detail panel.
      </>
    ),
    action: { label: "Set up alerts", dialog: "settings" },
  },
  {
    id: "failsafe",
    led: "led-warn",
    title: "Fail-safe by design",
    shot: "standby",
    body: (
      <>
        A watchdog warns the instant a camera drops, a feed freezes or a printer stops answering,
        nothing fails silently. Watching only stands down on a positive "not printing" signal, so a
        lost feed keeps watching rather than going blind.
      </>
    ),
  },
  {
    id: "customise",
    led: "led-on",
    title: "Make it yours",
    shot: "customise",
    body: (
      <>
        Reorder, pin and hide monitors and cameras with the ▦ Customise toggle, and switch between
        light, dark and your own custom themes. Your layout and theme sync to every browser that opens
        the hub.
      </>
    ),
    action: { label: "Open settings", dialog: "settings" },
  },
  {
    id: "integrate",
    led: "led-infer",
    title: "Automate & integrate",
    hubOnly: true,
    body: (
      <>
        On the hub, drive PrintGuard from a <strong>REST API</strong> or an <strong>MCP</strong>{" "}
        server with scoped tokens (read ⊂ control ⊂ manage), and surface every monitor in{" "}
        <strong>Home Assistant</strong> over MQTT.{" "}
        <a className={link} href={docs("api.md")} target="_blank" rel="noreferrer">
          API reference ↗
        </a>
      </>
    ),
    action: { label: "Manage access", dialog: "settings" },
  },
  {
    id: "plugins",
    led: "led-infer",
    title: "Plugins",
    shot: "plugins",
    body: (
      <>
        Add a panel to the dashboard or a job on the hub, from the catalogue or any GitHub repo.
        Plugins are third-party code, so they run in a sandbox with only what you grant them.{" "}
        <strong>Picture in picture</strong>, <strong>Alert sounds</strong>, <strong>Progress reports</strong>{" "}
        and <strong>Spotify</strong> come as standard.{" "}
        <a className={link} href={docs("plugins.md")} target="_blank" rel="noreferrer">
          Writing one ↗
        </a>
      </>
    ),
    action: { label: "Browse plugins", dialog: "settings" },
  },
  {
    id: "privacy",
    led: "led-on",
    title: "Your frames stay yours",
    body: (
      <>
        Inference runs entirely on your hardware, in this browser in local mode or on your hub. No
        frames, snapshots or scores are ever sent to a third party.
      </>
    ),
  },
  {
    id: "report",
    led: "led-warn",
    title: "Something broken?",
    body: (
      <>
        Report a bug from the <BugIcon className="inline h-[1.15em] w-[1.15em] align-[-0.2em]" /> chip in the header,
        anonymously, no account needed. A diagnostics bundle goes with it, with every credential stripped and no
        camera frames. Download the same bundle from that dialog to read it or send it somewhere else yourself.
      </>
    ),
    action: { label: "Report a bug", dialog: "report" },
  },
];
