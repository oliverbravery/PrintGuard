import { useEffect, useState } from "react";
import { useStore } from "../store";
import { Wordmark } from "./Header";

const REPO_URL = "https://github.com/oliverbravery/PrintGuard";
const MODEL_URL = "https://github.com/oliverbravery/Edge-FDM-Fault-Detection";

function ModeCard({
  number,
  title,
  tagline,
  lines,
  footer,
  onPick,
  href,
  index,
}: {
  number: string;
  title: string;
  tagline: string;
  lines: string[];
  footer: string;
  onPick?: () => void;
  href?: string;
  index: number;
}) {
  const className =
    "panel tile reveal relative block text-left p-7 sm:p-9 cursor-pointer hover:border-accent transition-colors group w-full";
  const style = { "--i": index } as React.CSSProperties;
  const inner = (
    <>
      <span className="corner corner-tl" />
      <span className="corner corner-tr" />
      <span className="corner corner-bl" />
      <span className="corner corner-br" />
      <div className="mono text-[0.65rem] text-text-2 mb-6">{number}</div>
      <h2 className="display text-4xl font-bold mb-1 group-hover:text-accent transition-colors">{title}</h2>
      <p className="display text-sm text-accent tracking-[0.14em] mb-5">{tagline}</p>
      <ul className="space-y-1.5">
        {lines.map((line) => (
          <li key={line} className="text-sm text-text-1 flex gap-2">
            <span className="text-accent mt-[1px]">›</span>
            {line}
          </li>
        ))}
      </ul>
      <div className="mt-7 display text-xs tracking-[0.2em] text-text-2 group-hover:text-accent transition-colors">
        {footer}
      </div>
    </>
  );
  return href ? (
    <a className={className} style={style} href={href} target="_blank" rel="noreferrer">
      {inner}
    </a>
  ) : (
    <button className={className} style={style} onClick={onPick}>
      {inner}
    </button>
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
      <div className="flex items-center gap-2.5 mb-2">
        <span className={`led ${led}`} />
        <h3 className="display text-sm font-semibold tracking-[0.2em]">{title}</h3>
      </div>
      <p className="text-[0.84rem] text-text-1 leading-relaxed">{body}</p>
    </div>
  );
}

export function Home() {
  const chooseMode = useStore((s) => s.chooseMode);
  const [hubUp, setHubUp] = useState(true);
  useEffect(() => {
    fetch("api/health")
      .then((r) => setHubUp(r.ok))
      .catch(() => setHubUp(false));
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      <div className="px-6 py-5 flex items-center justify-between">
        <Wordmark />
        <a className="mono text-[0.65rem] text-text-2 hover:text-accent transition-colors" href={REPO_URL} target="_blank" rel="noreferrer">
          GITHUB ↗
        </a>
      </div>

      <section className="px-6 pt-10 sm:pt-16 pb-10 text-center">
        <p className="mono text-[0.65rem] text-text-2 tracking-[0.32em] mb-6 reveal">FDM FAILURE DETECTION · LOCAL FIRST</p>
        <h1 className="display text-[2.7rem] sm:text-7xl font-bold leading-[0.95] mb-6 reveal" style={{ "--i": 1 } as React.CSSProperties}>
          EVERY LAYER WATCHED.
          <br />
          <span className="text-accent">EVERY FAILURE CAUGHT.</span>
        </h1>
        <p className="text-[0.95rem] sm:text-lg text-text-1 max-w-2xl mx-auto reveal" style={{ "--i": 2 } as React.CSSProperties}>
          PrintGuard watches your printer cameras with an on-device vision model, pauses the printer
          through OctoPrint or Klipper when a defect holds, and pushes a snapshot to your phone.
          No cloud, no subscription — your frames stay yours.
        </p>
        <div className="flex items-center justify-center gap-5 sm:gap-12 mt-9">
          <Spec index={3} value="≈5 MB" label="model" />
          <Spec index={4} value="0" label="frames to cloud" />
          <Spec index={5} value="2" label="operating modes" />
          <Spec index={6} value="GPL-2.0" label="licence" />
        </div>
      </section>

      <section className="px-4 sm:px-6 pb-12 mx-auto w-full max-w-5xl">
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Feature
            index={2}
            led="led-infer"
            title="Detect"
            body="A compact encoder scores every frame against failure prototypes, scheduled fairly across all your cameras."
          />
          <Feature
            index={3}
            led="led-on"
            title="Act"
            body="A sustained defect pauses or cancels the print through OctoPrint or Klipper — and inference rests while the printer is idle."
          />
          <Feature
            index={4}
            led="led-bad"
            title="Alert"
            body="The moment a defect holds, a snapshot lands on your phone over ntfy, Telegram or Discord."
          />
          <Feature
            index={5}
            led="led-warn"
            title="Fail safe"
            body="A watchdog warns the second a camera drops, a feed freezes or your printer stops answering. Nothing fails silently."
          />
        </div>
      </section>

      <div className="flex-1 grid place-items-center px-4 pb-16">
        <div className="w-full max-w-3xl">
          <p className="display text-center text-sm tracking-[0.3em] text-text-2 mb-8 reveal" style={{ "--i": 6 } as React.CSSProperties}>
            SELECT OPERATING MODE
          </p>
          <div className="grid sm:grid-cols-2 gap-4">
            <ModeCard
              index={7}
              number="01"
              title="Local"
              tagline="This device watches"
              lines={[
                "Inference runs in this browser",
                "Frames never leave the device",
                "Uses this device's cameras",
              ]}
              footer="START →"
              onPick={() => chooseMode("local")}
            />
            {hubUp ? (
              <ModeCard
                index={8}
                number="02"
                title="Hub"
                tagline="The server watches"
                lines={[
                  "Inference runs on the server",
                  "RTSP and published streams",
                  "Monitors with every tab closed",
                ]}
                footer="START →"
                onPick={() => chooseMode("hub")}
              />
            ) : (
              <ModeCard
                index={8}
                number="02"
                title="Hub"
                tagline="The server watches"
                lines={[
                  "Runs on your own hardware",
                  "RTSP and published streams",
                  "Monitors with every tab closed",
                ]}
                footer="SELF-HOST WITH DOCKER →"
                href={`${REPO_URL}#quick-start`}
              />
            )}
          </div>
        </div>
      </div>

      <footer className="hairline px-6 py-5 flex flex-wrap items-center justify-center gap-x-7 gap-y-2">
        <a className="mono text-[0.66rem] text-text-2 hover:text-accent transition-colors" href={REPO_URL} target="_blank" rel="noreferrer">
          github.com/oliverbravery/PrintGuard
        </a>
        <a className="mono text-[0.66rem] text-text-2 hover:text-accent transition-colors" href={MODEL_URL} target="_blank" rel="noreferrer">
          model: Edge-FDM-Fault-Detection
        </a>
      </footer>
    </div>
  );
}
