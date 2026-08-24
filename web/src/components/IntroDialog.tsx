import { useState } from "react";
import { INTRO } from "../guide";
import { useStore } from "../store";
import { Dialog } from "./Dialog";
import { GuideEntry } from "./GuideDialog";
import { Progress } from "./Progress";

export function IntroDialog() {
  const [page, setPage] = useState(0);
  const openDialog = useStore((s) => s.openDialog);
  const close = () => openDialog(null);
  const last = page === INTRO.length - 1;
  return (
    <Dialog title="How PrintGuard works" onClose={close}>
      <div className="space-y-5">
        <div aria-live="polite" className="sm:min-h-[13rem]">
          <GuideEntry key={INTRO[page].id} section={INTRO[page]} lead />
        </div>
        <footer className="hairline flex items-center gap-2 pt-4">
          <Progress value={page + 1} total={INTRO.length} className="flex-1" />
          {page > 0 && (
            <button className="btn" onClick={() => setPage(page - 1)}>
              Back
            </button>
          )}
          <button className="btn" onClick={close}>
            {last ? "Close" : "Skip"}
          </button>
          {!last && (
            <button className="btn btn-primary" onClick={() => setPage(page + 1)}>
              Next →
            </button>
          )}
        </footer>
      </div>
    </Dialog>
  );
}
