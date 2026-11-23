import { Bug } from "lucide-react";
import type { ReactNode } from "react";
import { ModelPicker } from "./components/ModelPicker";
import { NewTab } from "./components/NewTab";
import type { Target } from "./components/Page";
import { ReviewOptIn } from "./components/ReviewOptIn";
import type { SHOT_SIZES } from "./guideShots";

const REPO = "https://github.com/oliverbravery/PrintGuard";
const docs = (page: string) => `${REPO}/blob/main/docs/${page}`;
const link = "text-accent underline hover:opacity-80";

export interface GuideSection {
  id: string;
  led: string;
  title: string;
  body: ReactNode;
  shot?: keyof typeof SHOT_SIZES;
  visual?: ReactNode;
  action?: Target & { label: string };
}

const WATCH_STATES: { led: string; when: string; then: string }[] = [
  { led: "led-on", when: "Printing, or no printer linked", then: "Watching and scoring every frame" },
  { led: "led-off", when: "Printer reports idle, paused or errored", then: "On standby, saving CPU" },
];

export const INTRO: GuideSection[] = [
  {
    id: "what",
    led: "led-infer",
    title: "What PrintGuard does",
    shot: "alert",
    body: (
      <>
        PrintGuard runs a vision model locally on your own hardware to watch your printer cameras for failures. If a
        defect stays on screen for long enough, it pauses or cancels the print and sends you a snapshot alert. Your
        frames stay on your network and nothing leaves unless it goes to your own alert channels, your MQTT broker, or
        frames you choose to share for model training.
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
        A camera can be any USB webcam plugged into the hub or an RTSP, RTMP, MJPEG or WebRTC (WHEP) stream. Connecting
        a printer is optional, though linking one lets PrintGuard see when it's actually printing and stop it if a print
        goes bad.
      </>
    ),
  },
  {
    id: "monitors",
    led: "led-infer",
    title: "Monitors bring them together",
    shot: "tuning",
    body: (
      <>
        A monitor links one camera (and optionally one printer) and holds its own alert threshold, consecutive frame
        count and defect action. You can adjust all of these per monitor in the Tune and Configure tabs.
      </>
    ),
  },
  {
    id: "watching",
    led: "led-warn",
    title: "When detection runs",
    shot: "standby",
    body: (
      <>
        A monitor only goes on standby when its linked printer explicitly tells PrintGuard it isn't printing, so idle
        printers don't waste CPU. If the printer drops off the network mid-print, PrintGuard keeps watching just in case.
      </>
    ),
    visual: (
      <ul className="space-y-2">
        {WATCH_STATES.map((state) => (
          <li key={state.led} className="flex gap-3 border border-line-0 px-3.5 py-2.5">
            <span className={`led ${state.led} mt-[0.4rem]`} />
            <div className="min-w-0">
              <div className="text-sm text-text-0">{state.when}</div>
              <div className="text-sm text-text-2">{state.then}</div>
            </div>
          </li>
        ))}
      </ul>
    ),
  },
  {
    id: "model",
    led: "led-infer",
    title: "Pick a detection model",
    body: (
      <>
        Standard catches the most failures and is the best default. Light trades some accuracy for around 2.5x the speed
        if you're on slower hardware or watching several cameras. You can switch models any time under Settings, in
        Detection.
      </>
    ),
    visual: <ModelPicker />,
  },
  {
    id: "review",
    led: "led-on",
    title: "Review finished prints",
    body: (
      <>
        The Standard and Light models were trained on over 9,000 frames sent in by PrintGuard users. I couldn't have
        built them without that data. After each print, PrintGuard keeps a handful of frames locally in the monitor's
        Review tab so you can label and send them for future models. Nothing leaves your hub unless you press Send, and
        uploads are anonymous with a random hub ID and no monitor names, camera URLs or credentials.
      </>
    ),
    visual: <ReviewOptIn />,
  },
  {
    id: "start",
    led: "led-on",
    title: "Ready to start",
    shot: "checklist",
    body: (
      <>
        Add a camera first, then create a monitor to start watching it. Hook up your printer and an alert channel like
        ntfy or Telegram to get automatic pauses and phone notifications. You can open the full guide any time from the
        ? button in the top bar.
      </>
    ),
    action: { label: "Register a camera", dialog: "camera" },
  },
];

export const GUIDE: GuideSection[] = [
  {
    id: "what",
    led: "led-infer",
    title: "What PrintGuard does",
    body: (
      <>
        PrintGuard watches your printer cameras with a local vision model, pauses or cancels the print if a failure
        holds, and sends a snapshot to your phone. There's no cloud account or subscription, and your camera frames stay
        on your own hardware unless they're going to your alert channels, your MQTT broker, or frames you manually send
        in to help train future models.
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
        A camera can be a USB webcam plugged into the hub, an RTSP, RTMP, MJPEG or WebRTC (WHEP) stream URL, or even the
        camera on the phone or laptop you're using right now. Printers that expose a webcam get added automatically. The
        model only looks inside the crop box you set in the camera editor, so crop it tightly around the build plate.
      </>
    ),
    action: { label: "Open cameras", to: "/cameras" },
  },
  {
    id: "printers",
    led: "led-on",
    title: "Printers",
    shot: "printers",
    body: (
      <>
        Connect <strong>OctoPrint</strong>, <strong>Klipper (Moonraker)</strong>, <strong>Creality</strong>,{" "}
        <strong>Elegoo</strong>, <strong>Prusa (PrusaLink)</strong>, <strong>Bambu Lab</strong> or{" "}
        <strong>Ultimaker</strong> so PrintGuard can read print status, progress and temperatures, preheat the heaters
        and pause or cancel a failing print. Linking a printer is optional; without one, a monitor still watches and
        alerts.{" "}
        <a className={link} href={docs("printers.md")} target="_blank" rel="noreferrer">
          Setup guides <NewTab />
        </a>
      </>
    ),
    action: { label: "Open printers", to: "/printers" },
  },
  {
    id: "prints",
    led: "led-on",
    title: "Print library",
    shot: "prints",
    body: (
      <>
        Drop sliced files onto the library to inspect their toolpath in your browser, rename them and tweak first-layer
        temperatures before uploading. Each saved file keeps its preview, estimated time and filament usage from your
        slicer. Tag a file with the printers it was sliced for so it can only start on those machines. When you start a
        print, the bed camera pops up first so you can make sure the plate is clear.
      </>
    ),
    action: { label: "Open the library", to: "/prints" },
  },
  {
    id: "monitors",
    led: "led-infer",
    title: "Monitors",
    shot: "alert",
    body: (
      <>
        A monitor links one camera (and optionally one printer) together with its own thresholds and defect response.
        PrintGuard shares inference time fairly across every active monitor. Each monitor shows whether it's watching,
        on standby or has no signal, and switches to defect during an alert.
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
        Every frame gets a score for how likely the print is failing. <strong>Alert threshold</strong> sets how high
        that score needs to go, and <strong>consecutive detections</strong> sets how many flagged frames in a row it
        takes before PrintGuard acts. You can dial both in per monitor under Tune.
      </>
    ),
  },
  {
    id: "models",
    led: "led-infer",
    title: "Detection models",
    body: (
      <>
        PrintGuard ships with three models so you can trade accuracy against speed. Settings charts all three against
        Obico's open models on unseen printers, right next to your host's live speed readout, making it easy to pick the
        right one for your hardware.{" "}
        <a
          className={link}
          href="https://oliverbravery.uk/blog/rebuilding-printguards-brain"
          target="_blank"
          rel="noreferrer"
        >
          How the new models were trained <NewTab />
        </a>
      </>
    ),
    action: { label: "Choose a model", to: "/settings/detection" },
  },
  {
    id: "alerts",
    led: "led-bad",
    title: "Alerts",
    shot: "alerts",
    body: (
      <>
        Set up <strong>ntfy</strong>, <strong>Pushover</strong>, <strong>Telegram</strong>, <strong>Discord</strong> or{" "}
        <strong>Desktop notifications</strong> (in the desktop app) and PrintGuard sends a snapshot the moment a defect
        triggers. Remember to switch push notifications on for each monitor in its Configure tab.
      </>
    ),
    action: { label: "Set up alerts", to: "/settings/alerts" },
  },
  {
    id: "failsafe",
    led: "led-warn",
    title: "Built to fail safe",
    shot: "standby",
    body: (
      <>
        An independent watchdog warns you if a camera disconnects, a feed freezes or a printer stops replying for longer
        than the grace period (two minutes by default). Monitors only go on standby when a printer confirms it isn't
        printing, so a lost connection won't quietly stop detection.
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
        Hit the six-dot button above the fleet list to reorder, pin or hide monitors, and switch between Light, Dark, Glass or your own
        custom colour themes. Both your layout and theme are saved on the hub so every device you open it on matches.
      </>
    ),
    action: { label: "Open settings", to: "/settings/appearance" },
  },
  {
    id: "integrate",
    led: "led-infer",
    title: "Automate & integrate",
    body: (
      <>
        Control PrintGuard from scripts or AI agents using the <strong>REST API</strong> or <strong>MCP</strong>{" "}
        server with scoped tokens (read ⊂ control ⊂ manage), or expose every monitor in{" "}
        <strong>Home Assistant</strong> via MQTT discovery.{" "}
        <a className={link} href={docs("api.md")} target="_blank" rel="noreferrer">
          API reference <NewTab />
        </a>
      </>
    ),
    action: { label: "Manage access", to: "/settings/api" },
  },
  {
    id: "plugins",
    led: "led-infer",
    title: "Plugins",
    shot: "plugins",
    body: (
      <>
        Extend the dashboard or hub with plugins from the catalogue, a GitHub repo or a zip file. Everything runs in a
        sandbox and can only touch what you approve. <strong>Picture in picture</strong>, <strong>Alert sounds</strong>,{" "}
        <strong>Progress reports</strong> and <strong>Spotify</strong> are ready to install in the catalogue.{" "}
        <a className={link} href={docs("plugin-development.md")} target="_blank" rel="noreferrer">
          Writing a plugin <NewTab />
        </a>
      </>
    ),
    action: { label: "Browse plugins", to: "/settings/plugins" },
  },
  {
    id: "privacy",
    led: "led-on",
    title: "Your frames stay yours",
    body: (
      <>
        All inference happens on your own machine, and defect snapshots only go to the alert channels and MQTT broker
        you configure. PrintGuard keeps a handful of frames locally after each print so you can review them and
        optionally send them to me to help train future models. Nothing is ever sent unless you click Send, and you can
        switch the review flow off under Settings, in Storage.
      </>
    ),
  },
  {
    id: "report",
    led: "led-warn",
    title: "Report a bug",
    body: (
      <>
        Found a problem? Hit the <Bug className="inline h-[1.15em] w-[1.15em] align-[-0.2em]" aria-hidden /> icon in
        the top bar to send me an anonymous bug report, no GitHub account required. It attaches a diagnostics bundle
        with all passwords, keys and tokens stripped out, and no camera frames unless you attach them yourself. You can
        also download the exact same zip to read it first or post it on GitHub yourself.
      </>
    ),
    action: { label: "Report a bug", dialog: "report" },
  },
];
