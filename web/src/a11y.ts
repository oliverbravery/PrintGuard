import { useLayoutEffect, useRef, type KeyboardEvent } from "react";

const CONTROLS = "a[href], button:enabled, input:enabled:not([hidden]), select:enabled, textarea:enabled";

export function useFocusKept<Group extends HTMLElement>() {
  const group = useRef<Group>(null);
  const heldFocus = group.current?.contains(document.activeElement) ?? false;
  useLayoutEffect(() => {
    if (!heldFocus || group.current?.contains(document.activeElement)) return;
    Array.from(group.current?.querySelectorAll<HTMLElement>(CONTROLS) ?? []).at(-1)?.focus();
  });
  return group;
}

export function markLastInput(): void {
  const mark = (input: "pointer" | "keyboard") => () => (document.documentElement.dataset.input = input);
  window.addEventListener("pointerdown", mark("pointer"), true);
  window.addEventListener("keydown", mark("keyboard"), true);
}

export function cardButton(onActivate: () => void, label: string) {
  return {
    role: "button" as const,
    tabIndex: 0,
    "aria-label": label,
    onClick: onActivate,
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onActivate();
      }
    },
  };
}
