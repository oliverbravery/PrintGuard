import { useStore } from "../store";
import { SaveStatus } from "./SaveStatus";
import { Toggle } from "./Toggle";

export function UpdatesTab() {
  const { engine, send, isPending, openDialog, updateSettings } = useStore();
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
        Checks the public GitHub releases once a day, from the hub. No telemetry is sent.
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn" disabled={isPending("update.check")} onClick={() => send({ cmd: "update.check" })}>
          {isPending("update.check") ? "Checking…" : "Check now"}
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
