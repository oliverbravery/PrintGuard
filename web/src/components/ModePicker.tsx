import { useStore } from "../store";
import { Wordmark } from "./Header";

function ModeCard({
  title,
  tagline,
  lines,
  onPick,
  index,
}: {
  title: string;
  tagline: string;
  lines: string[];
  onPick: () => void;
  index: number;
}) {
  return (
    <button
      className="panel tile reveal relative text-left p-7 sm:p-9 cursor-pointer hover:border-accent transition-colors group w-full"
      style={{ "--i": index } as React.CSSProperties}
      onClick={onPick}
    >
      <span className="corner corner-tl" />
      <span className="corner corner-tr" />
      <span className="corner corner-bl" />
      <span className="corner corner-br" />
      <div className="mono text-[0.65rem] text-text-2 mb-6">0{index + 1}</div>
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
        START →
      </div>
    </button>
  );
}

export function ModePicker() {
  const chooseMode = useStore((s) => s.chooseMode);
  return (
    <div className="min-h-screen flex flex-col">
      <div className="px-6 py-5 flex items-center justify-between">
        <Wordmark />
        <span className="mono text-[0.65rem] text-text-2">FDM FAILURE DETECTION</span>
      </div>
      <div className="flex-1 grid place-items-center px-4 pb-16">
        <div className="w-full max-w-3xl">
          <p className="display text-center text-sm tracking-[0.3em] text-text-2 mb-8 reveal">
            SELECT OPERATING MODE
          </p>
          <div className="grid sm:grid-cols-2 gap-4">
            <ModeCard
              index={0}
              title="Local"
              tagline="This device watches"
              lines={[
                "Inference runs in this browser",
                "Frames never leave the device",
                "Uses this device's cameras",
              ]}
              onPick={() => chooseMode("local")}
            />
            <ModeCard
              index={1}
              title="Hub"
              tagline="The server watches"
              lines={[
                "Inference runs on the server",
                "RTSP and published streams",
                "Monitors with every tab closed",
              ]}
              onPick={() => chooseMode("hub")}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
