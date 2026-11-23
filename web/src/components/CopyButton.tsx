import { useState } from "react";

async function copyText(text: string, button: HTMLButtonElement): Promise<void> {
  if (navigator.clipboard) return navigator.clipboard.writeText(text);
  const field = document.createElement("textarea");
  field.value = text;
  field.readOnly = true;
  field.className = "sr-only";
  button.after(field);
  field.focus();
  field.setSelectionRange(0, text.length);
  const copied = document.execCommand("copy");
  field.remove();
  button.focus();
  if (!copied) throw new Error("this browser refused the copy");
}

export function CopyButton({ text }: { text: string }) {
  const [label, setLabel] = useState("Copy");
  return (
    <button
      className="btn"
      onClick={(event) =>
        copyText(text, event.currentTarget).then(
          () => setLabel("Copied"),
          () => setLabel("Select it to copy"),
        )
      }
    >
      {label}
    </button>
  );
}
