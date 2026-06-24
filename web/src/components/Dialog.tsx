import { useEffect, useId, useRef, type ReactNode } from "react";

let openModals = 0;

/** Modal shell built on the native `<dialog>` element: the browser owns the focus trap,
 *  Esc handling, top-layer rendering, background `inert` and focus return to the opener.
 *  Closing always flows through `onClose` (which unmounts this component); the effect
 *  cleanup calls `.close()` to restore focus. A module counter ref-locks body scroll so
 *  nested modals (a side panel opening a dialog) stay locked until the last one closes. */
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

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const titleId = useId();
  return (
    <Modal onClose={onClose} labelledBy={titleId}>
      <div className="panel rise-in w-full sm:max-w-lg max-h-[92vh] overflow-y-auto rounded-b-none sm:rounded-md">
        <div className="flex items-center justify-between px-5 py-3 border-b border-line-0">
          <h2 id={titleId} className="display text-sm font-semibold text-text-1">
            {title}
          </h2>
          <button
            type="button"
            className="text-text-2 hover:text-accent text-xl leading-none cursor-pointer"
            onClick={onClose}
            aria-label="Close dialog"
          >
            ×
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </Modal>
  );
}
