import { useStore } from "../store";
import { Progress } from "./Progress";
import type { DialogKind } from "../store";

interface Step {
  n: number;
  title: string;
  why: string;
  done: boolean;
  dialog: DialogKind;
  optional?: boolean;
}

function StepRow({ step, primary }: { step: Step; primary: boolean }) {
  const openDialog = useStore((s) => s.openDialog);
  return (
    <li className="flex items-center gap-3 rounded border border-line-0 bg-ink-0/40 px-3.5 py-2.5">
      <span
        className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-[0.72rem] font-semibold ${
          step.done ? "bg-accent text-on-accent" : "border border-line-1 text-text-2"
        }`}
      >
        {step.done ? "✓" : step.n}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm text-text-0">
          {step.title}
          {step.optional && <span className="label">optional</span>}
        </div>
        <div className="text-xs text-text-2">{step.why}</div>
      </div>
      {step.done ? (
        <span className="label shrink-0 text-accent">done</span>
      ) : (
        <button
          className={`btn shrink-0 ${primary ? "btn-primary" : ""}`}
          onClick={() => openDialog(step.dialog)}
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
      dialog: "cameras",
    },
    {
      n: 2,
      title: "Connect a printer",
      why: "Lets PrintGuard pause or cancel on a defect.",
      done: engine.printers.length > 0,
      dialog: "printers",
      optional: true,
    },
    {
      n: 3,
      title: "Set up alerts",
      why: "Get a snapshot on your phone when a defect holds.",
      done: Object.keys(engine.settings.notifiers).length > 0,
      dialog: "settings",
      optional: true,
    },
    {
      n: 4,
      title: "Add a monitor",
      why: "Bind a camera and start watching.",
      done: engine.monitors.length > 0,
      dialog: "monitor",
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  const primaryStep = steps.find((s) => !s.optional && !s.done) ?? steps.find((s) => !s.done);

  return (
    <div className="reveal grid place-items-center py-16 sm:py-20">
      <div className="panel relative w-full max-w-xl p-7 sm:p-9">
        <span className="corner corner-tl !border-text-2" />
        <span className="corner corner-tr !border-text-2" />
        <span className="corner corner-bl !border-text-2" />
        <span className="corner corner-br !border-text-2" />
        <div className="mb-1 flex items-center gap-2.5">
          <span className="led led-infer" />
          <h2 className="display text-xl font-bold">GET PRINTGUARD WATCHING</h2>
        </div>
        <p className="mb-5 text-sm text-text-1">
          Register a camera and add a monitor to start watching. Connect a printer and alerts for the
          full safety net.
        </p>
        <Progress value={doneCount} total={steps.length} className="mb-4" />
        <ol className="space-y-2.5">
          {steps.map((step) => (
            <StepRow key={step.n} step={step} primary={step === primaryStep} />
          ))}
        </ol>
        <button
          className="mt-5 text-xs text-text-2 underline transition-colors hover:text-accent"
          onClick={() => openDialog("intro")}
        >
          New here? How PrintGuard works →
        </button>
      </div>
    </div>
  );
}
