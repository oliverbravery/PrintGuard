import { Camera, Layers, type LucideIcon, Plus, Printer, Settings } from "lucide-react";
import { type DialogKind, useStore } from "../store";

interface Destination {
  dialog: DialogKind;
  label: string;
  icon: LucideIcon;
  primary?: boolean;
  iconOnly?: boolean;
}

const DESTINATIONS: Destination[] = [
  { dialog: "cameras", label: "Cameras", icon: Camera },
  { dialog: "printers", label: "Printers", icon: Printer },
  { dialog: "prints", label: "Prints", icon: Layers },
  { dialog: "monitor", label: "Monitor", icon: Plus, primary: true },
  { dialog: "settings", label: "Settings", icon: Settings, iconOnly: true },
];

export function HeaderActions() {
  const openDialog = useStore((s) => s.openDialog);
  return (
    <nav className="hidden items-center gap-2 lg:flex xl:gap-3" aria-label="Primary">
      {DESTINATIONS.map(({ dialog, label, icon: Icon, primary, iconOnly }) => (
        <button
          key={dialog}
          className={`btn ${primary ? "btn-primary" : ""} ${iconOnly ? "self-stretch px-2.5" : ""}`}
          aria-label={iconOnly ? label : undefined}
          title={iconOnly ? label : undefined}
          onClick={() => openDialog(dialog)}
        >
          {iconOnly ? <Icon size={16} aria-hidden /> : primary ? `+ ${label}` : label}
        </button>
      ))}
    </nav>
  );
}

export function AppNav() {
  const openDialog = useStore((s) => s.openDialog);
  return (
    <nav className="app-nav" aria-label="Primary">
      {DESTINATIONS.map(({ dialog, label, icon: Icon, primary }) => (
        <button key={dialog} className="nav-item" data-primary={primary || undefined} onClick={() => openDialog(dialog)}>
          <span className="nav-icon">
            <Icon size={22} aria-hidden />
          </span>
          {label}
        </button>
      ))}
    </nav>
  );
}
