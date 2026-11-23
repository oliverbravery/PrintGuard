import { ChevronLeft } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { type DialogKind, useStore } from "../store";
import { ConfirmButton } from "./ConfirmButton";

export type Target = { to: string; dialog?: never } | { dialog: Exclude<DialogKind, null>; to?: never };

export function useGo(): (target: Target) => void {
  const navigate = useNavigate();
  const openDialog = useStore((s) => s.openDialog);
  return (target) => {
    if (target.dialog) return openDialog(target.dialog);
    openDialog(null);
    navigate(target.to);
  };
}

export interface Back {
  to: string;
  label: string;
}

export function BackLink({ back, className = "" }: { back: Back; className?: string }) {
  return (
    <Link to={back.to} className={`page-back ${className}`}>
      <ChevronLeft size={16} aria-hidden />
      {back.label}
    </Link>
  );
}

export function Page({
  title,
  back,
  actions,
  subview = false,
  phoneBack,
  children,
}: {
  title: string;
  back?: Back;
  actions?: ReactNode;
  subview?: boolean;
  phoneBack?: Back;
  children: ReactNode;
}) {
  return (
    <div className="page" data-subview={subview || undefined}>
      <title>{`${title} · PrintGuard`}</title>
      <div className="page-head">
        {phoneBack && <BackLink back={phoneBack} className="md:hidden" />}
        {back && <BackLink back={back} className={phoneBack ? "max-md:hidden" : ""} />}
        <h1 tabIndex={-1} className="page-title">
          {title}
        </h1>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function Split({ list, detail, detailShown }: { list: ReactNode; detail: ReactNode; detailShown: boolean }) {
  return (
    <div className="page-fill grid md:grid-cols-[16rem_minmax(0,1fr)] xl:grid-cols-[22rem_minmax(0,1fr)] grid-rows-[minmax(0,1fr)]">
      <div className={`relative min-w-0 border-rule md:border-r overflow-y-auto ${detailShown ? "max-md:hidden" : ""}`}>{list}</div>
      <div className={`relative min-w-0 overflow-y-auto ${detailShown ? "" : "max-md:hidden"}`}>{detail}</div>
    </div>
  );
}

type Removable = { kind: "camera" | "monitor" | "print" | "printer"; id: string };

function RemoveButton({ kind, id }: Removable) {
  const cmd = `${kind}.remove`;
  const send = useStore((s) => s.send);
  const removing = useStore((s) => s.isPending(cmd, id));
  return (
    <ConfirmButton disabled={removing} onConfirm={() => send({ cmd, id })}>
      {removing ? "Removing…" : "Remove"}
    </ConfirmButton>
  );
}

export function DetailHead({ title, remove, children }: { title: string; remove?: Removable; children?: ReactNode }) {
  return (
    <div className="flex min-h-12 flex-wrap items-center gap-2 border-b border-rule px-4 py-2">
      <h2 data-heading tabIndex={-1} className="min-w-0 flex-1 truncate text-base font-bold">
        {title}
      </h2>
      {children}
      {remove && <RemoveButton {...remove} />}
    </div>
  );
}

export function ListHead({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex min-h-11 items-stretch border-b border-rule bg-ink-1">
      <div className="flex min-w-0 flex-1 items-center gap-2 px-4 py-1.5">
        <h2 className="label flex-1 text-text-1">{title}</h2>
        {children}
      </div>
      {action}
    </div>
  );
}

const ADD_CELL = "cell-action cell-action-primary flex items-center self-stretch px-4 text-xs";

export function AddCell({ label, to, current, onClick }: { label: string; to?: string; current?: boolean; onClick?: () => void }) {
  return to ? (
    <Link to={to} aria-label={label} aria-current={current ? "page" : undefined} className={ADD_CELL}>
      + Add
    </Link>
  ) : (
    <button type="button" aria-label={label} className={ADD_CELL} onClick={onClick}>
      + Add
    </button>
  );
}
