import { useEffect, useRef, useState, type ButtonHTMLAttributes } from "react";

const CONFIRM_WINDOW_MS = 4000;

export function useConfirm(onConfirm: () => void) {
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    if (!armed) return;
    const revert = setTimeout(() => setArmed(false), CONFIRM_WINDOW_MS);
    return () => clearTimeout(revert);
  }, [armed]);

  return {
    armed,
    disarm: () => setArmed(false),
    press: () => {
      setArmed(!armed);
      if (armed) onConfirm();
    },
  };
}

export function ConfirmButton({
  onConfirm,
  className = "",
  children,
  ...button
}: { onConfirm: () => void } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onClick" | "type">) {
  const { armed, disarm, press } = useConfirm(onConfirm);
  const ref = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!armed) return;
    const disarmOnPressElsewhere = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) disarm();
    };
    const disarmOnFocusElsewhere = (event: FocusEvent) => {
      if (!(event.target as Node).contains(ref.current)) disarm();
    };
    document.addEventListener("pointerdown", disarmOnPressElsewhere);
    document.addEventListener("focusin", disarmOnFocusElsewhere);
    return () => {
      document.removeEventListener("pointerdown", disarmOnPressElsewhere);
      document.removeEventListener("focusin", disarmOnFocusElsewhere);
    };
  }, [armed]);

  return (
    <>
      <span role="status" className="sr-only">
        {armed && "Press again to confirm"}
      </span>
      <button
        {...button}
        ref={ref}
        type="button"
        className={`btn btn-danger ${armed ? "btn-armed" : ""} ${className}`}
        onClick={() => {
          ref.current?.focus();
          press();
        }}
        onKeyDown={(event) => {
          if (!armed || event.key !== "Escape") return;
          event.preventDefault();
          event.stopPropagation();
          disarm();
        }}
      >
        <span className="grid place-items-center *:[grid-area:1/1]">
          <span className={armed ? "invisible" : ""}>{children}</span>
          <span className={armed ? "" : "invisible"}>Confirm</span>
        </span>
      </button>
    </>
  );
}
