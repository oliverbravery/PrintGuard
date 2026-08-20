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
  action?: { label: string; dialog: DialogKind };
  hubOnly?: boolean;
}

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
    body: (
      <>
        Every frame is scored against failure prototypes. <strong>Alert threshold</strong> sets how
        high that score must reach, <strong>sensitivity</strong> widens or narrows the margin, and a
        defect must hold for a number of <strong>consecutive detections</strong> before PrintGuard
        acts. <strong>On sustained defect</strong> chooses nothing, pause or cancel, and{" "}
        <strong>cooldown</strong> is the quiet window afterwards. Tune these per monitor from its
        detail panel.
      </>
    ),
  },
  {
    id: "alerts",
    led: "led-bad",
    title: "Alerts",
    body: (
      <>
        Add a notification channel, whether <strong>ntfy</strong>, <strong>Telegram</strong>,{" "}
        <strong>Discord</strong>, or <strong>native notifications</strong> in the desktop app, and
        PrintGuard sends a snapshot the moment a defect holds. Turn notifications on per monitor in
        its detail panel.
      </>
    ),
    action: { label: "Set up alerts", dialog: "settings" },
  },
  {
    id: "failsafe",
    led: "led-warn",
    title: "Fail-safe by design",
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
    body: (
      <>
        Add a panel to the dashboard, or a job that runs on the hub, from the catalogue or from any
        GitHub repository. Plugins are third-party code, so they run in a sandbox with no network
        and no access to your credentials, cameras or tokens, and only do what you grant them.{" "}
        <strong>Picture in picture</strong>, <strong>Alert sounds</strong> and <strong>Progress reports</strong>{" "}
        come as standard, floating a camera above your other windows, sounding a horn the moment a defect
        is caught and sending a tally of how a print is going through your alert channels.{" "}
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
        anonymously, no account needed. Describe what happened, attach screenshots if they help, and optionally
        leave an email for follow-up. A diagnostics bundle goes with it, with every credential stripped and no
        camera frames. Download the same bundle from that dialog to read it or send it somewhere else yourself.
      </>
    ),
    action: { label: "Report a bug", dialog: "report" },
  },
];
