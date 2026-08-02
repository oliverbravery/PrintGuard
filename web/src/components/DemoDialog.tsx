import { useStore } from "../store";
import { Dialog } from "./Dialog";

const LIMITS: { title: string; app: string }[] = [
  {
    title: "This tab has to stay open",
    app: "The app keeps watching around the clock and pauses a print while you sleep.",
  },
  {
    title: "This device's webcams only",
    app: "The app watches RTSP, MJPEG and WebRTC streams, and your printer's own camera.",
  },
  {
    title: "OctoPrint and Klipper only",
    app: "The app also drives Bambu Lab, Prusa and Elegoo printers.",
  },
  {
    title: "Browser-speed inference",
    app: "The app uses your GPU or NPU, and watches several cameras at once.",
  },
];

export function DemoDialog() {
  const dismissDemo = useStore((s) => s.dismissDemo);
  const leaveMode = useStore((s) => s.leaveMode);
  return (
    <Dialog title="Live demo" onClose={dismissDemo}>
      <div className="space-y-5">
        <div>
          <div className="mb-1.5 flex items-center gap-2.5">
            <span className="led led-infer" />
            <h3 className="display text-base font-bold">THE REAL ENGINE, IN THIS TAB</h3>
          </div>
          <p className="text-sm leading-relaxed text-text-1">
            The vision model is loaded here and scores your webcam live. Nothing is installed and no
            frame leaves this browser.
          </p>
        </div>

        <div>
          <span className="label mb-2 block">What the demo cannot do</span>
          <ul className="space-y-2">
            {LIMITS.map((limit) => (
              <li
                key={limit.title}
                className="flex gap-3 rounded border border-line-0 bg-ink-0/40 px-3.5 py-2.5"
              >
                <span className="led led-warn mt-[0.4rem]" />
                <div className="min-w-0">
                  <div className="text-sm text-text-0">{limit.title}</div>
                  <div className="text-xs leading-relaxed text-text-2">{limit.app}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-text-2">
          Telegram alerts, the REST API, MCP and the Home Assistant bridge are app only too.
        </p>

        <div className="hairline flex flex-wrap gap-2.5 pt-4">
          <button className="btn btn-primary" onClick={dismissDemo}>
            Explore the demo →
          </button>
          <button className="btn" onClick={leaveMode}>
            Install PrintGuard
          </button>
        </div>
      </div>
    </Dialog>
  );
}
