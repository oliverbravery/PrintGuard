import { type KeyboardEvent, type ReactNode, type Ref, useEffect, useRef } from "react";
import { useScrollEdges } from "../scroll";

export interface Tab<T extends string> {
  id: T;
  label: string;
  badge?: string;
}

export function Tabs<T extends string>({
  prefix,
  label,
  tabs,
  value,
  onChange,
  cells = false,
}: {
  prefix: string;
  label: string;
  tabs: Tab<T>[];
  value: T;
  onChange: (id: T) => void;
  cells?: boolean;
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
    <div
      ref={ref}
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={cells ? "tabs-cells scroll-x" : "scroll-x flex border-b border-line-0"}
    >
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
          className="tab"
        >
          {t.label}
          {t.badge && (
            <>
              <span aria-hidden className="ml-1.5 inline-block size-1.5 bg-accent align-middle" />
              <span className="sr-only">, {t.badge}</span>
            </>
          )}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({
  prefix,
  id,
  className,
  ref,
  children,
}: {
  prefix: string;
  id: string;
  className?: string;
  ref?: Ref<HTMLDivElement>;
  children: ReactNode;
}) {
  return (
    <div ref={ref} role="tabpanel" id={`${prefix}-panel-${id}`} aria-labelledby={`${prefix}-tab-${id}`} tabIndex={0} className={className}>
      {children}
    </div>
  );
}
