import { type KeyboardEvent, type ReactNode, useEffect, useRef } from "react";
import { useScrollEdges } from "../scroll";

export interface Tab<T extends string> {
  id: T;
  label: string;
}

export function Tabs<T extends string>({
  prefix,
  label,
  tabs,
  value,
  onChange,
}: {
  prefix: string;
  label: string;
  tabs: Tab<T>[];
  value: T;
  onChange: (id: T) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useScrollEdges(ref, tabs.length);

  useEffect(() => {
    const frame = requestAnimationFrame(() =>
      document.getElementById(`${prefix}-tab-${value}`)?.scrollIntoView({ block: "nearest", inline: "nearest" }),
    );
    return () => cancelAnimationFrame(frame);
  }, [prefix, value]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const i = tabs.findIndex((t) => t.id === value);
    const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    let next = i;
    if (delta) next = (i + delta + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    onChange(tabs[next].id);
    document.getElementById(`${prefix}-tab-${tabs[next].id}`)?.focus();
  };

  return (
    <div ref={ref} role="tablist" aria-label={label} onKeyDown={onKeyDown} className="scroll-x flex border-b border-line-0">
      {tabs.map((t) => (
        <button
          key={t.id}
          id={`${prefix}-tab-${t.id}`}
          type="button"
          role="tab"
          aria-selected={value === t.id}
          aria-controls={`${prefix}-panel-${t.id}`}
          tabIndex={value === t.id ? 0 : -1}
          onClick={() => onChange(t.id)}
          className={`-mb-px shrink-0 cursor-pointer whitespace-nowrap border-b-2 px-3 py-2.5 text-xs transition-colors ${
            value === t.id ? "border-accent text-text-0" : "border-transparent text-text-2 hover:text-text-1"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ prefix, id, className, children }: { prefix: string; id: string; className?: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`${prefix}-panel-${id}`} aria-labelledby={`${prefix}-tab-${id}`} tabIndex={0} className={className}>
      {children}
    </div>
  );
}
