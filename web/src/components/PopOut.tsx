import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

interface PictureInPicture {
  requestWindow(options: { width: number; height: number }): Promise<Window & typeof globalThis>;
}

const api = (): PictureInPicture | undefined => (window as unknown as { documentPictureInPicture?: PictureInPicture }).documentPictureInPicture;

export const popOutSupported = (): boolean => api() !== undefined;

const WIDTH = 520;
const FEED_RATIO = 9 / 16;

function hug(target: Window & typeof globalThis): () => void {
  const observer = new target.ResizeObserver(() => {
    const content = target.document.documentElement.scrollHeight;
    const wanted = content + (target.outerHeight - target.innerHeight);
    if (content > 0 && wanted !== target.outerHeight) target.resizeTo(target.outerWidth, wanted);
  });
  observer.observe(target.document.body);
  return () => observer.disconnect();
}

function dress(target: Document): void {
  const root = document.documentElement;
  target.documentElement.dataset.theme = root.dataset.theme ?? "";
  target.documentElement.style.cssText = root.style.cssText;
  for (const sheet of document.querySelectorAll<HTMLElement>('style, link[rel="stylesheet"]')) {
    target.head.appendChild(sheet.cloneNode(true));
  }
  target.body.className = "bg-ink-0 overflow-hidden";
}

export function usePopOut(open: boolean, onClose: () => void): Document | null {
  const [pip, setPip] = useState<Document | null>(null);

  useEffect(() => {
    const service = api();
    if (!open || !service) return;
    let window_: Window | null = null;
    let unhug: (() => void) | null = null;
    let cancelled = false;
    void service.requestWindow({ width: WIDTH, height: Math.round(WIDTH * FEED_RATIO) }).then((created) => {
      if (cancelled) return created.close();
      window_ = created;
      dress(created.document);
      unhug = hug(created);
      created.addEventListener("pagehide", onClose);
      setPip(created.document);
    }, onClose);
    return () => {
      cancelled = true;
      unhug?.();
      setPip(null);
      window_?.close();
    };
  }, [open]);

  return pip;
}

export function PopOut({ document: target, children }: { document: Document; children: React.ReactNode }) {
  return createPortal(children, target.body);
}
