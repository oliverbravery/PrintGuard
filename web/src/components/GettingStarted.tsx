import { savedChannels, useStore } from "../store";
import { type Target, useGo } from "./Page";
import { Progress } from "./Progress";

type Step = Target & {
  n: number;
  title: string;
  why: string;
  done: boolean;
  optional?: boolean;
};

function StepRow({ step, primary }: { step: Step; primary: boolean }) {
  const go = useGo();
  return (
    <li className="flex items-center gap-3 border-b border-line-0 px-4 py-3">
      <span
        className={`mono grid size-7 shrink-0 place-items-center text-xs font-semibold ${
          step.done ? "bg-text-0 text-ink-0" : "border border-line-1 text-text-1"
        }`}
      >
        {step.done ? "✓" : step.n}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm font-semibold">
          {step.title}
          {step.optional && <span className="label">optional</span>}
        </div>
        <div className="text-sm text-text-2">{step.why}</div>
      </div>
      {step.done ? (
        <span className="label shrink-0 text-ok">done</span>
      ) : (
        <button
          className={`btn shrink-0 ${primary ? "btn-primary" : ""}`}
          aria-label={`Open ${step.title}`}
          onClick={() => go(step)}
        >
          Open
        </button>
      )}
    </li>
  );
}

export function GettingStarted() {
  const engine = useStore((s) => s.engine);
  const openDialog = useStore((s) => s.openDialog);
  if (!engine) return null;
  const steps: Step[] = [
    {
      n: 1,
      title: "Register a camera",
      why: "The video source PrintGuard watches.",
      done: engine.cameras.length > 0,
      to: "/cameras/new",
    },
    {
      n: 2,
      title: "Frame the print",
      why: "The model watches a square, so crop it to the print.",
      done: engine.cameras.some((c) => c.crop),
      to: engine.cameras[0] ? `/cameras/${engine.cameras[0].id}` : "/cameras/new",
      optional: true,
    },
    {
      n: 3,
      title: "Connect a printer",
      why: "Lets PrintGuard pause or cancel on a defect.",
      done: engine.printers.length > 0,
      to: "/printers/new",
      optional: true,
    },
    {
      n: 4,
      title: "Set up alerts",
      why: "Get a snapshot on your phone when a defect holds.",
      done: Object.keys(savedChannels(engine)).length > 0,
      to: "/settings/alerts",
      optional: true,
    },
    {
      n: 5,
      title: "Add a monitor",
      why: "Bind a camera and start watching.",
      done: engine.monitors.length > 0,
      dialog: "monitor",
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  const primaryStep = steps.find((s) => !s.optional && !s.done) ?? steps.find((s) => !s.done);

  return (
    <div className="mx-auto w-full min-w-0 max-w-2xl px-4 py-10 sm:py-16">
      <div className="border border-rule">
        <div className="border-b border-rule px-4 py-4">
          <h2 className="text-xl font-bold tracking-[-0.02em]">Get PrintGuard watching</h2>
        <p className="mt-1 text-sm text-text-1">
          Register a camera and add a monitor to start watching. Connect a printer and alerts for the
          full safety net.
        </p>
        <Progress label="Setup progress" value={doneCount} total={steps.length} className="mt-4" />
        </div>
        <ol>
          {steps.map((step) => (
            <StepRow key={step.n} step={step} primary={step === primaryStep} />
          ))}
        </ol>
        <button className="btn-inline m-4" onClick={() => openDialog("intro")}>
          How PrintGuard works
        </button>
      </div>
    </div>
  );
}
