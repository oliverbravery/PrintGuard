import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

interface PictureInPicture {
  requestWindow(options: { width: number; height: number }): Promise<Window>;
}

const api = (): PictureInPicture | undefined => (window as unknown as { documentPictureInPicture?: PictureInPicture }).documentPictureInPicture;

export const popOutSupported = (): boolean => api() !== undefined;

function dress(target: Document): void {
  const root = document.documentElement;
  target.documentElement.dataset.theme = root.dataset.theme ?? "";
  target.documentElement.style.cssText = root.style.cssText;
  for (const sheet of document.querySelectorAll<HTMLElement>('style, link[rel="stylesheet"]')) {
    target.head.appendChild(sheet.cloneNode(true));
  }
  target.body.className = "bg-ink-0 p-3";
}

export function usePopOut(open: boolean, onClose: () => void): Document | null {
  const [pip, setPip] = useState<Document | null>(null);

  useEffect(() => {
    const service = api();
    if (!open || !service) return;
    let window_: Window | null = null;
    let cancelled = false;
    void service.requestWindow({ width: 520, height: 420 }).then((created) => {
      if (cancelled) return created.close();
      window_ = created;
      dress(created.document);
      created.addEventListener("pagehide", onClose);
      setPip(created.document);
    }, onClose);
    return () => {
      cancelled = true;
      setPip(null);
      window_?.close();
    };
  }, [open]);

  return pip;
}

export function PopOut({ document: target, children }: { document: Document; children: React.ReactNode }) {
  return createPortal(children, target.body);
}
