import { useShallow } from "zustand/react/shallow";
import { useStore } from "../store";
import { Toggle } from "./Toggle";

export function AutoUpdateToggle() {
  const { on, updateSettings } = useStore(
    useShallow((s) => ({
      on: Boolean(s.engine?.settings.auto_update && s.engine.settings.update_check),
      updateSettings: s.updateSettings,
    })),
  );
  return (
    <div className="space-y-3">
      <Toggle
        label="Install updates automatically"
        on={on}
        onChange={(next) => updateSettings(next ? { auto_update: true, update_check: true } : { auto_update: false }, "updates")}
      />
      <span className="block text-sm text-text-2">
        Downloads each release in the background and asks before restarting PrintGuard to install it. If you don't
        answer, it installs by itself once no monitor is watching a print.
      </span>
    </div>
  );
}
