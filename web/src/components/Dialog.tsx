import type { ReactNode } from "react";

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="backdrop flex items-end sm:items-center justify-center p-0 sm:p-6" onClick={onClose}>
      <div
        className="panel rise-in w-full sm:max-w-lg max-h-[92vh] overflow-y-auto rounded-b-none sm:rounded-md"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-line-0">
          <h2 className="display text-sm font-semibold text-text-1">{title}</h2>
          <button className="text-text-2 hover:text-accent text-xl leading-none cursor-pointer" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
