import type { KeyboardEvent } from "react";

/** Props that make a non-button element (a clickable card) behave as a button for keyboard
 *  and assistive-tech users: focusable, named, and activated by Enter or Space. Spread onto
 *  the clickable element in place of a bare `onClick`. */
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
