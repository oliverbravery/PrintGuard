import { GUIDE, type GuideSection } from "../guide";
import { useStore } from "../store";
import { Dialog } from "./Dialog";

const REPO = "https://github.com/oliverbravery/PrintGuard";
const MODEL = "https://github.com/oliverbravery/Edge-FDM-Fault-Detection";

export function GuideEntry({ section, lead }: { section: GuideSection; lead?: boolean }) {
  const openDialog = useStore((s) => s.openDialog);
  const { action } = section;
  return (
    <section className="reveal">
      <div className="mb-1.5 flex items-center gap-2.5">
        <span className={`led ${section.led}`} />
        <h3 className={lead ? "display text-base font-bold" : "display text-sm font-semibold tracking-[0.14em]"}>
          {section.title}
        </h3>
      </div>
      <p className={`leading-relaxed text-text-1 ${lead ? "text-sm" : "text-[0.84rem]"}`}>{section.body}</p>
      {section.shot && (
        <figure className="shot">
          <img className="shot-dark" src={`guide/${section.shot}-dark.jpg`} alt="" loading="lazy" />
          <img className="shot-light" src={`guide/${section.shot}-light.jpg`} alt="" loading="lazy" />
        </figure>
      )}
      {section.visual && <div className="mt-3">{section.visual}</div>}
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
          What everything on the dashboard means, and what you can do with it. Use a section's action
          to jump straight in.
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
