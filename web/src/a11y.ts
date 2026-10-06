import type { KeyboardEvent } from "react";

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
