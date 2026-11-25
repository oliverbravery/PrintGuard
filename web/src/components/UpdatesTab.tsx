import { useShallow } from "zustand/react/shallow";
import { useStore } from "../store";
import { AutoUpdateToggle } from "./AutoUpdateToggle";
import { SaveStatus } from "./SaveStatus";
import { Toggle } from "./Toggle";

export function UpdatesTab() {
  const { engine, send, checking, openDialog, updateSettings } = useStore(
    useShallow((s) => ({
      engine: s.engine,
      send: s.send,
      checking: s.isPending("update.check"),
      openDialog: s.openDialog,
      updateSettings: s.updateSettings,
    })),
  );
  const updateCheck = engine?.settings.update_check ?? true;
  return (
    <div className="space-y-3">
      <Toggle
        label="Automatically check for updates"
        on={updateCheck}
        onChange={(on) => {
          updateSettings({ update_check: on }, "updates");
          if (on && !engine?.update) send({ cmd: "update.check" });
        }}
      />
      <span className="block text-sm text-text-2">
        Checks GitHub releases once a day straight from your hub, with no telemetry.
      </span>
      {engine?.installs_updates && <AutoUpdateToggle />}
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn" disabled={checking} onClick={() => send({ cmd: "update.check" })}>
          {checking ? "Checking…" : "Check now"}
        </button>
        <button className={`btn ${engine?.update?.available ? "btn-primary" : ""}`} onClick={() => openDialog("update")}>
          {engine?.update?.available ? `Update to v${engine.update.latest}` : "Release notes"}
        </button>
        <span className="text-sm text-text-2">
          {engine?.version && `v${engine.version}`}
          {engine?.update && !engine.update.available && " · up to date"}
        </span>
      </div>
      <div className="flex justify-end">
        <SaveStatus scope="settings:updates" />
      </div>
    </div>
  );
}
