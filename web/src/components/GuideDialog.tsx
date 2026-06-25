import { GUIDE, type GuideSection } from "../guide";
import { useStore } from "../store";
import { Dialog } from "./Dialog";

const REPO = "https://github.com/oliverbravery/PrintGuard";
const MODEL = "https://github.com/oliverbravery/Edge-FDM-Fault-Detection";

function GuideEntry({ section }: { section: GuideSection }) {
  const openDialog = useStore((s) => s.openDialog);
  const { action } = section;
  return (
    <section className="reveal">
      <div className="mb-1.5 flex items-center gap-2.5">
        <span className={`led ${section.led}`} />
        <h3 className="display text-sm font-semibold tracking-[0.14em]">{section.title}</h3>
      </div>
      <p className="text-[0.84rem] leading-relaxed text-text-1">{section.body}</p>
      {action && (
        <button className="btn mt-2.5" onClick={() => openDialog(action.dialog)}>
          {action.label} →
        </button>
      )}
    </section>
  );
}

export function GuideDialog() {
  const openDialog = useStore((s) => s.openDialog);
  const mode = useStore((s) => s.mode);
  const sections = GUIDE.filter((s) => !s.hubOnly || mode === "hub");
  return (
    <Dialog title="Guide" size="wide" onClose={() => openDialog(null)}>
      <div className="space-y-6">
        <p className="text-sm text-text-1">
          PrintGuard catches print failures for you. Here's what everything means and what you can do
          — use a section's action to jump straight in.
        </p>
        {sections.map((section) => (
          <GuideEntry key={section.id} section={section} />
        ))}
        <footer className="hairline flex flex-wrap gap-x-6 gap-y-2 pt-4">
          <a
            className="mono text-[0.66rem] text-text-2 transition-colors hover:text-accent"
            href={REPO}
            target="_blank"
            rel="noreferrer"
          >
            Documentation ↗
          </a>
          <a
            className="mono text-[0.66rem] text-text-2 transition-colors hover:text-accent"
            href={MODEL}
            target="_blank"
            rel="noreferrer"
          >
            The vision model ↗
          </a>
        </footer>
      </div>
    </Dialog>
  );
}
