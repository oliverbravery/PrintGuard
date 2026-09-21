import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

let openModals = 0;

export function Modal({
  onClose,
  variant = "center",
  labelledBy,
  children,
}: {
  onClose: () => void;
  variant?: "center" | "sheet";
  labelledBy?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    // The opener is captured before `showModal` moves focus inside, and refocused on
    // unmount: React detaches the node during the passive-effect flush, so the dialog's
    // own focus-return has nothing to restore to by the time cleanup runs.
    const opener = document.activeElement as HTMLElement | null;
    if (!dialog.open) dialog.showModal();
    if (openModals++ === 0) document.body.style.overflow = "hidden";

    const onCancel = (event: Event) => {
      event.preventDefault();
      onCloseRef.current();
    };
    const onLightDismiss = (event: MouseEvent) => {
      if (event.target === dialog) onCloseRef.current();
    };
    dialog.addEventListener("cancel", onCancel);
    dialog.addEventListener("click", onLightDismiss);

    return () => {
      dialog.removeEventListener("cancel", onCancel);
      dialog.removeEventListener("click", onLightDismiss);
      if (--openModals === 0) document.body.style.overflow = "";
      dialog.close();
      opener?.focus?.();
    };
  }, []);

  return (
    <dialog ref={ref} aria-labelledby={labelledBy} className={`modal modal-${variant}`}>
      {children}
    </dialog>
  );
}

export function CloseButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      className="-my-2 -mr-2.5 grid h-10 w-10 shrink-0 cursor-pointer place-items-center rounded text-text-2 transition-colors hover:text-accent"
      onClick={onClick}
      aria-label={label}
    >
      <X size={20} aria-hidden />
    </button>
  );
}

export function Dialog({
  title,
  onClose,
  size = "default",
  fixed = false,
  toolbar,
  children,
}: {
  title: string;
  onClose: () => void;
  size?: "default" | "wide";
  fixed?: boolean;
  toolbar?: ReactNode;
  children: ReactNode;
}) {
  const titleId = useId();
  return (
    <Modal onClose={onClose} labelledBy={titleId}>
      <div
        className={`panel rise-in flex w-full flex-col overflow-hidden ${size === "wide" ? "sm:max-w-2xl" : "sm:max-w-lg"} ${
          fixed ? "h-[min(92dvh,46rem)]" : "max-h-[92dvh]"
        }`}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line-0 px-5 py-3">
          <h2 id={titleId} className="display min-w-0 truncate text-sm font-semibold text-text-1">
            {title}
          </h2>
          <CloseButton label="Close dialog" onClick={onClose} />
        </div>
        {toolbar && <div className="shrink-0 px-5">{toolbar}</div>}
        <div className={`min-h-0 flex-1 p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] sm:pb-5 ${fixed ? "" : "overflow-y-auto overscroll-contain"}`}>
          {children}
        </div>
      </div>
    </Modal>
  );
}

export function Sheet({
  title,
  onClose,
  closeLabel,
  width = "sm:w-[460px]",
  lead,
  meta,
  children,
}: {
  title: string;
  onClose: () => void;
  closeLabel: string;
  width?: string;
  lead?: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
}) {
  const titleId = useId();
  return (
    <Modal onClose={onClose} variant="sheet" labelledBy={titleId}>
      <aside className={`slide-in flex h-full w-full flex-col border-l border-line-0 bg-ink-1 ${width}`}>
        <div className="flex shrink-0 items-center gap-2.5 border-b border-line-0 px-5 py-3.5">
          {lead}
          <h2 id={titleId} className="display min-w-0 flex-1 truncate text-lg font-semibold">
            {title}
          </h2>
          {meta}
          <CloseButton label={closeLabel} onClick={onClose} />
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain">{children}</div>
      </aside>
    </Modal>
  );
}
