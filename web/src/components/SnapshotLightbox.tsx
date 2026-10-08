import { useId, type ReactNode } from "react";
import { useStore } from "../store";
import { Modal } from "./Dialog";

export function SnapshotLightbox({ snapshotId, caption, color, onClose }: { snapshotId: string; caption: ReactNode; color?: string; onClose: () => void }) {
  const url = useStore((s) => s.snapshotCache[snapshotId]);
  const captionId = useId();
  return (
    <Modal onClose={onClose} labelledBy={captionId}>
      <button type="button" className="fixed inset-0 grid place-items-center bg-ink-0/90 p-6" onClick={onClose} aria-label="Close snapshot">
        {url ? (
          <img src={url} alt="" className="max-h-full max-w-full object-contain" />
        ) : (
          <span className="mono boot-cursor text-[0.68rem] uppercase tracking-[0.2em] text-text-2">loading picture</span>
        )}
        <span id={captionId} className="mono absolute left-6 top-6 text-sm" style={{ color }}>
          {caption}
        </span>
      </button>
    </Modal>
  );
}
