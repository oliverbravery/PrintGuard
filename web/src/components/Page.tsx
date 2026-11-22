import { ChevronLeft } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { type DialogKind, useStore } from "../store";

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
  titleHidden = false,
  phoneBack,
  children,
}: {
  title: string;
  back?: Back;
  actions?: ReactNode;
  subview?: boolean;
  titleHidden?: boolean;
  phoneBack?: Back;
  children: ReactNode;
}) {
  return (
    <div className="page" data-subview={subview || undefined}>
      <title>{`${title} · PrintGuard`}</title>
      {titleHidden ? (
        <h1 tabIndex={-1} className="sr-only">
          {title}
        </h1>
      ) : (
        <div className="page-head">
          {phoneBack && <BackLink back={phoneBack} className="md:hidden" />}
          {back && <BackLink back={back} className={phoneBack ? "max-md:hidden" : ""} />}
          <h1 tabIndex={-1} className="page-title">
            {title}
          </h1>
          {actions && <div className="page-actions">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

export function Split({ list, detail, detailShown }: { list: ReactNode; detail: ReactNode; detailShown: boolean }) {
  return (
    <div className="page-fill grid md:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)] grid-rows-[minmax(0,1fr)]">
      <div className={`min-w-0 border-rule md:border-r overflow-y-auto ${detailShown ? "max-md:hidden" : ""}`}>{list}</div>
      <div className={`min-w-0 overflow-y-auto ${detailShown ? "" : "max-md:hidden"}`}>{detail}</div>
    </div>
  );
}

export function DetailHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex min-h-12 flex-wrap items-center gap-2 border-b border-rule px-4 py-2">
      <h2 data-heading tabIndex={-1} className="min-w-0 flex-1 truncate text-base font-bold">
        {title}
      </h2>
      {children}
    </div>
  );
}

export function ListHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex min-h-11 items-center gap-2 border-b border-rule bg-ink-1 px-4 py-1.5">
      <h2 className="label flex-1 text-text-1">{title}</h2>
      {children}
    </div>
  );
}
