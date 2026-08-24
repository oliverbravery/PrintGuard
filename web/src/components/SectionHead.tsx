import type { ReactNode } from "react";

export function SectionHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex items-center gap-3 mb-2.5">
      <h2 className="plate display text-xs font-semibold tracking-[0.24em] text-text-2">{title}</h2>
      <div className="hairline flex-1" />
      {children}
    </div>
  );
}
